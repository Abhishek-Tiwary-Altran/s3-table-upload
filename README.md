# S3 Tables Loader

A Python tool that takes a local CSV file, creates an Amazon S3 Tables (Iceberg) table, and loads the data into it using Amazon Athena. Everything is driven by a simple JSON config file.

## What This Tool Does

1. Reads your CSV file and auto-detects column names and types
2. Uploads the CSV to an S3 bucket
3. Creates an S3 Table Bucket, namespace, and Iceberg table
4. Loads the CSV data into the Iceberg table via Athena
5. Verifies the data was loaded correctly
6. Cleans up temporary resources

---

## Prerequisites

### 1. AWS Account Setup

If you don't have an AWS account, create one at https://aws.amazon.com/. You'll need a user with programmatic access.

### 2. Create an IAM User with Required Permissions

1. Go to the AWS Console → IAM → Users → Create User
2. Give it a name (e.g., `s3-tables-loader-user`)
3. Attach the following AWS managed policies:
   - `AmazonS3FullAccess`
   - `AmazonAthenaFullAccess`
   - `AWSGlueConsoleFullAccess`
   - `AmazonS3TablesFullAccess`
4. Create the user and save the Access Key ID and Secret Access Key

### 3. Install the AWS CLI

**macOS:**
```bash
brew install awscli
```

**Windows:**

Download and run the MSI installer from https://aws.amazon.com/cli/

Or via PowerShell:
```powershell
msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi
```
After installation, close and reopen your terminal (Command Prompt or PowerShell).

**Linux (Ubuntu/Debian):**
```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

Verify installation on any platform:
```bash
aws --version
```

### 4. Configure AWS Credentials

Run the following and enter your Access Key ID, Secret Access Key, and region:

```bash
aws configure
```

Example:
```
AWS Access Key ID: AKIA...
AWS Secret Access Key: wJal...
Default region name: us-east-1
Default output format: json
```

Verify it works:
```bash
aws sts get-caller-identity
```

### 5. Install Python 3.9+

**macOS:**
```bash
brew install python
```

**Windows:**

Download from https://www.python.org/downloads/ and run the installer.
Check "Add Python to PATH" during installation.

Verify in Command Prompt or PowerShell:
```powershell
python --version
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

---

## Setup

### 1. Clone or Download This Project

Place all files in a directory on your machine.

### 2. Create a Virtual Environment

**macOS / Linux:**
```bash
python3 -m venv .venv
```

**Windows (Command Prompt or PowerShell):**
```powershell
python -m venv .venv
```

### 3. Activate the Virtual Environment

**macOS / Linux:**
```bash
source .venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
.venv\Scripts\activate.bat
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

If you get a PowerShell execution policy error, run this first:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 4. Install Dependencies

Once the virtual environment is activated (you'll see `(.venv)` in your prompt):

```bash
pip install -r requirements.txt
```

---

## AWS Resource Setup (One-Time)

### 1. Create an S3 Bucket for CSV Storage and Athena Results

```bash
aws s3 mb s3://your-bucket-name --region us-east-1
```

Replace `your-bucket-name` with a globally unique name.

### 2. Integrate S3 Tables with AWS Analytics Services

This is required so Athena can query your S3 Tables.

**Option A (Recommended):** Create your first table bucket via the AWS Console:
1. Go to S3 Console → Table Buckets → Create Table Bucket
2. Make sure "Enable integration with AWS analytics services" is checked
3. This automatically sets up Glue Data Catalog integration for your region

**Option B:** If you already have a table bucket created programmatically, follow the manual integration steps at:
https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-aws.html

### 3. Set Up Athena Query Results Location

1. Go to the Athena Console
2. Click "Settings" (top right)
3. Set "Query result location" to `s3://your-bucket-name/athena-results/`
4. Save

---

## Configuration

Edit `config.json` with your values:

```json
{
    "csv_file_path": "path/to/your-file.csv",
    "s3_upload_bucket": "your-bucket-name",
    "s3_upload_prefix": "Dataset/",
    "table_bucket_name": "your-table-bucket-name",
    "namespace": "your_namespace",
    "table_name": "your_table_name",
    "region": "us-east-1",
    "athena_workgroup": "primary",
    "athena_output_location": "s3://your-bucket-name/athena-results/"
}
```

| Field | Description |
|---|---|
| `csv_file_path` | Path to the CSV file on your local machine |
| `s3_upload_bucket` | S3 bucket where the CSV will be uploaded |
| `s3_upload_prefix` | Folder path inside the bucket (include trailing `/`) |
| `table_bucket_name` | Name for the S3 Table Bucket (lowercase, hyphens only) |
| `namespace` | Namespace inside the table bucket (lowercase, underscores only) |
| `table_name` | Table name (lowercase, underscores only) |
| `region` | AWS region (e.g., `us-east-1`) |
| `athena_workgroup` | Athena workgroup name (use `primary` if unsure) |
| `athena_output_location` | S3 path for Athena query results |

**Important naming rules:**
- Table bucket names: lowercase letters, numbers, and hyphens only (3-63 chars)
- Namespace and table names: lowercase letters, numbers, and underscores only. No capital letters — Athena will reject them.

**File path notes:**
- **macOS / Linux:** Use forward slashes — `data/my-file.csv`
- **Windows:** Use either forward slashes `data/my-file.csv` or escaped backslashes `data\\my-file.csv`

---

## Running the Script

Make sure your virtual environment is activated (you should see `(.venv)` in your prompt).

**macOS / Linux:**
```bash
python s3_table_loader.py --config config.json
```

**Windows (Command Prompt or PowerShell):**
```powershell
python s3_table_loader.py --config config.json
```

The script will output progress for each step:

```
=== Detect Schema ===
  Detected 5 columns from CSV:
      1. id                  int
      2. name                string
      3. value               double
      ...

=== Upload CSV to S3 ===
  Upload complete.

=== Create S3 Table Bucket ===
  Created: arn:aws:s3tables:us-east-1:123456789:bucket/my-bucket

=== Create Namespace ===
  Created namespace: my_namespace

=== Create Iceberg Table ===
  Created table: arn:aws:s3tables:...

=== Load Data via Athena ===
  Row count: 1432
  Data loaded successfully!
  S3 Tables row count: 1432

=== All Done! ===
```

---

## Querying Your Data

After loading, you can query your table in the Athena Console:

```sql
SELECT * FROM "s3tablescatalog/your-table-bucket-name"."your_namespace"."your_table_name" LIMIT 10
```

---

## Loading Multiple CSV Files

Create a separate config file for each CSV:

**macOS / Linux:**
```bash
python s3_table_loader.py --config config-sales.json
python s3_table_loader.py --config config-inventory.json
```

**Windows:**
```powershell
python s3_table_loader.py --config config-sales.json
python s3_table_loader.py --config config-inventory.json
```

---

## Deactivating the Virtual Environment

When you're done, deactivate the virtual environment:

```bash
deactivate
```

This works the same on all platforms.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `NoCredentialsError` | Run `aws configure` and enter your credentials |
| `AccessDenied` on S3 | Check your IAM user has `AmazonS3FullAccess` policy |
| `InvalidRequestException` from Athena | Ensure Athena workgroup has a query results location set |
| Table not visible in Athena | Make sure S3 Tables is integrated with analytics services (see AWS Resource Setup step 2) |
| `GENERIC_INTERNAL_ERROR` in Athena | Table or column names may contain uppercase letters. Use only lowercase. |
| `ConflictException` | The table bucket, namespace, or table already exists. The script handles this gracefully and continues. |
| PowerShell `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| `python` not found on macOS/Linux | Use `python3` instead of `python` |
| `pip` not found | Use `pip3` instead, or ensure your virtual environment is activated |

---

## File Overview

| File | Purpose |
|---|---|
| `s3_table_loader.py` | Main script — creates S3 Table and loads CSV data |
| `config.json` | Configuration file with your settings |
| `requirements.txt` | Python dependencies |
| `README.md` | This file — setup and usage instructions |
| `create_s3_table.py` | Standalone script to create S3 Table only (no data loading) |
| `load_data_athena.py` | Standalone Athena data loading script (hardcoded config) |
