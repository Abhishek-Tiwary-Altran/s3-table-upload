"""
Generic S3 Tables Loader

Reads a local CSV file, auto-detects its schema, creates an S3 Table Bucket
with namespace and Iceberg table, uploads the CSV to S3, and loads data
into the Iceberg table via Athena.

Driven by a JSON config file. See config.json for an example.

Usage:
    python s3_table_loader.py --config config.json

Prerequisites:
    pip install boto3
"""

import argparse
import csv
import json
import os
import re
import sys
import time

import boto3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(path):
    with open(path) as f:
        cfg = json.load(f)
    required = [
        "csv_file_path", "s3_upload_bucket", "s3_upload_prefix",
        "table_bucket_name", "namespace", "table_name",
        "region", "athena_workgroup", "athena_output_location",
    ]
    missing = [k for k in required if k not in cfg]
    if missing:
        print(f"ERROR: Missing config keys: {missing}")
        sys.exit(1)
    return cfg


def sanitize_column_name(name):
    """Convert a CSV header into a valid Iceberg/Athena column name (lowercase, underscores)."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")
    return name or "col"


def detect_schema(csv_path, sample_rows=100):
    """Read CSV headers and sample rows to build an Iceberg schema.
    Returns (original_headers, schema_fields) where schema_fields is a list of dicts."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        raw_headers = next(reader)

        # Deduplicate sanitized names
        seen = {}
        sanitized = []
        for h in raw_headers:
            s = sanitize_column_name(h)
            if s in seen:
                seen[s] += 1
                s = f"{s}_{seen[s]}"
            else:
                seen[s] = 0
            sanitized.append(s)

        # Sample rows to guess types
        is_int = [True] * len(sanitized)
        is_float = [True] * len(sanitized)
        for i, row in enumerate(reader):
            if i >= sample_rows:
                break
            for j, val in enumerate(row):
                if j >= len(sanitized):
                    break
                val = val.strip()
                if val == "":
                    continue
                try:
                    int(val)
                except ValueError:
                    is_int[j] = False
                try:
                    float(val)
                except ValueError:
                    is_float[j] = False

    fields = []
    for idx, col in enumerate(sanitized):
        if is_int[idx]:
            col_type = "int"
        elif is_float[idx]:
            col_type = "double"
        else:
            col_type = "string"
        fields.append({
            "id": idx + 1,
            "name": col,
            "type": col_type,
            "required": False,
        })

    print(f"  Detected {len(fields)} columns from CSV:")
    for f in fields:
        print(f"    {f['id']:>3}. {f['name']:<40} {f['type']}")

    return raw_headers, sanitized, fields


def run_athena_query(client, query, cfg, database=None):
    """Execute an Athena query and wait for completion."""
    params = {
        "QueryString": query,
        "WorkGroup": cfg["athena_workgroup"],
        "ResultConfiguration": {"OutputLocation": cfg["athena_output_location"]},
    }
    ctx = {}
    if database:
        ctx["Database"] = database
    if ctx:
        params["QueryExecutionContext"] = ctx

    short = query.replace("\n", " ").strip()
    print(f"\n  Athena: {short[:150]}{'...' if len(short) > 150 else ''}")
    response = client.start_query_execution(**params)
    qid = response["QueryExecutionId"]

    while True:
        result = client.get_query_execution(QueryExecutionId=qid)
        state = result["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)

    if state != "SUCCEEDED":
        reason = result["QueryExecution"]["Status"].get("StateChangeReason", "Unknown")
        print(f"  FAILED: {reason}")
        return None, state

    print(f"  OK (QueryId: {qid})")
    return qid, state


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def upload_csv(cfg):
    """Upload the local CSV to S3."""
    print("\n=== Upload CSV to S3 ===")
    csv_path = cfg["csv_file_path"]
    filename = os.path.basename(csv_path)
    s3_key = cfg["s3_upload_prefix"].rstrip("/") + "/" + filename

    s3 = boto3.client("s3", region_name=cfg["region"])
    print(f"  Uploading {csv_path} -> s3://{cfg['s3_upload_bucket']}/{s3_key}")
    s3.upload_file(csv_path, cfg["s3_upload_bucket"], s3_key)
    print("  Upload complete.")
    return s3_key


def create_table_bucket(cfg):
    """Create S3 Table Bucket (or get existing ARN)."""
    print("\n=== Create S3 Table Bucket ===")
    client = boto3.client("s3tables", region_name=cfg["region"])
    name = cfg["table_bucket_name"]
    try:
        resp = client.create_table_bucket(name=name)
        arn = resp["arn"]
        print(f"  Created: {arn}")
        return arn
    except client.exceptions.ConflictException:
        print(f"  '{name}' already exists. Looking up ARN...")
        paginator = client.get_paginator("list_table_buckets")
        for page in paginator.paginate():
            for b in page["tableBuckets"]:
                if b["name"] == name:
                    print(f"  Found: {b['arn']}")
                    return b["arn"]
        print("  ERROR: Could not find table bucket.")
        sys.exit(1)


def create_namespace(cfg, table_bucket_arn):
    """Create namespace in the table bucket."""
    print("\n=== Create Namespace ===")
    client = boto3.client("s3tables", region_name=cfg["region"])
    ns = cfg["namespace"]
    try:
        client.create_namespace(tableBucketARN=table_bucket_arn, namespace=[ns])
        print(f"  Created namespace: {ns}")
    except client.exceptions.ConflictException:
        print(f"  Namespace '{ns}' already exists.")


def create_iceberg_table(cfg, table_bucket_arn, schema_fields):
    """Create the Iceberg table in S3 Tables."""
    print("\n=== Create Iceberg Table ===")
    client = boto3.client("s3tables", region_name=cfg["region"])
    try:
        resp = client.create_table(
            tableBucketARN=table_bucket_arn,
            namespace=cfg["namespace"],
            name=cfg["table_name"],
            format="ICEBERG",
            metadata={"iceberg": {"schema": {"fields": schema_fields}}},
        )
        print(f"  Created table: {resp.get('tableARN', 'N/A')}")
    except client.exceptions.ConflictException:
        print(f"  Table '{cfg['table_name']}' already exists.")


def load_data_via_athena(cfg, sanitized_cols, schema_fields):
    """Create temp external table, INSERT INTO Iceberg table, cleanup."""
    print("\n=== Load Data via Athena ===")
    athena = boto3.client("athena", region_name=cfg["region"])

    temp_db = "s3_table_loader_temp_db"
    temp_table = "temp_csv_import"
    csv_location = f"s3://{cfg['s3_upload_bucket']}/{cfg['s3_upload_prefix'].rstrip('/')}/"

    # 1. Create temp database
    print("\n--- Create temp Glue database ---")
    _, state = run_athena_query(athena, f"CREATE DATABASE IF NOT EXISTS {temp_db}", cfg)
    if state != "SUCCEEDED":
        sys.exit(1)

    # 2. Drop temp table if exists
    run_athena_query(athena, f"DROP TABLE IF EXISTS {temp_db}.{temp_table}", cfg, database=temp_db)

    # 3. Create external table — all columns as STRING for safe loading
    col_defs = ",\n    ".join(f"{c} string" for c in sanitized_cols)
    create_sql = f"""
CREATE EXTERNAL TABLE {temp_db}.{temp_table} (
    {col_defs}
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
ESCAPED BY '\\\\'
LINES TERMINATED BY '\\n'
LOCATION '{csv_location}'
TBLPROPERTIES ('skip.header.line.count'='1')
"""
    print("\n--- Create temp external table ---")
    _, state = run_athena_query(athena, create_sql, cfg, database=temp_db)
    if state != "SUCCEEDED":
        sys.exit(1)

    # 4. Verify row count
    print("\n--- Verify temp table ---")
    qid, state = run_athena_query(
        athena, f"SELECT COUNT(*) AS cnt FROM {temp_db}.{temp_table}", cfg, database=temp_db
    )
    if state == "SUCCEEDED" and qid:
        result = athena.get_query_results(QueryExecutionId=qid)
        rows = result["ResultSet"]["Rows"]
        if len(rows) > 1:
            print(f"  Row count: {rows[1]['Data'][0]['VarCharValue']}")

    # 5. Build INSERT INTO with type casting
    s3t_ref = f'"s3tablescatalog/{cfg["table_bucket_name"]}"."{cfg["namespace"]}"."{cfg["table_name"]}"'

    select_parts = []
    for col, field in zip(sanitized_cols, schema_fields):
        ftype = field["type"]
        if ftype == "int":
            select_parts.append(f"CAST(NULLIF(TRIM({col}), '') AS int)")
        elif ftype == "double":
            select_parts.append(f"CAST(NULLIF(TRIM({col}), '') AS double)")
        else:
            select_parts.append(col)

    select_clause = ",\n    ".join(select_parts)
    insert_sql = f"""
INSERT INTO {s3t_ref}
SELECT
    {select_clause}
FROM {temp_db}.{temp_table}
"""
    print("\n--- Insert data into S3 Tables Iceberg table ---")
    _, state = run_athena_query(athena, insert_sql, cfg)
    if state != "SUCCEEDED":
        print("  ERROR: Data insertion failed.")
        sys.exit(1)
    print("  Data loaded successfully!")

    # 6. Verify in S3 Tables
    print("\n--- Verify S3 Tables data ---")
    qid, state = run_athena_query(athena, f"SELECT COUNT(*) FROM {s3t_ref}", cfg)
    if state == "SUCCEEDED" and qid:
        result = athena.get_query_results(QueryExecutionId=qid)
        rows = result["ResultSet"]["Rows"]
        if len(rows) > 1:
            print(f"  S3 Tables row count: {rows[1]['Data'][0]['VarCharValue']}")

    qid, state = run_athena_query(athena, f"SELECT * FROM {s3t_ref} LIMIT 3", cfg)
    if state == "SUCCEEDED" and qid:
        result = athena.get_query_results(QueryExecutionId=qid)
        for row in result["ResultSet"]["Rows"]:
            vals = [d.get("VarCharValue", "") for d in row["Data"]]
            print(f"    {vals}")

    # 7. Cleanup
    print("\n--- Cleanup temp resources ---")
    run_athena_query(athena, f"DROP TABLE IF EXISTS {temp_db}.{temp_table}", cfg, database=temp_db)
    run_athena_query(athena, f"DROP DATABASE IF EXISTS {temp_db}", cfg)
    print("  Cleanup done.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generic S3 Tables Loader")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    args = parser.parse_args()

    cfg = load_config(args.config)
    csv_path = cfg["csv_file_path"]

    if not os.path.exists(csv_path):
        print(f"ERROR: CSV file not found: {csv_path}")
        sys.exit(1)

    print(f"Config loaded. CSV: {csv_path}")

    # Detect schema from CSV
    print("\n=== Detect Schema ===")
    raw_headers, sanitized_cols, schema_fields = detect_schema(csv_path)

    # Upload CSV to S3
    upload_csv(cfg)

    # Create S3 Table Bucket
    table_bucket_arn = create_table_bucket(cfg)

    # Create Namespace
    create_namespace(cfg, table_bucket_arn)

    # Create Iceberg Table
    create_iceberg_table(cfg, table_bucket_arn, schema_fields)

    # Load data via Athena
    load_data_via_athena(cfg, sanitized_cols, schema_fields)

    print("\n=== All Done! ===")
    print(f"Table: s3tablescatalog/{cfg['table_bucket_name']}.{cfg['namespace']}.{cfg['table_name']}")


if __name__ == "__main__":
    main()
