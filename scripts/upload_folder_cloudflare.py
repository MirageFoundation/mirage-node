#!/usr/bin/env python3
"""
Upload all images in a folder to Cloudflare Images and output the URLs.

Usage:
    conda run -n mirage-node python scripts/upload_folder_cloudflare.py /path/to/folder

Credentials loaded from ~/.mirage/env/backend.env (local docker config).

Output:
    Prints each uploaded file's URL, one per line.
    Also saves to upload_results.txt in the source folder.
"""

import os
import sys
import json
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico'}

def load_env_file(env_path: Path):
    """Load environment variables from a .env file."""
    if not env_path.exists():
        return
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


def get_credentials():
    """Get Cloudflare credentials from environment."""
    account_id = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '').strip()
    api_token = os.environ.get('CLOUDFLARE_API_TOKEN', '').strip()
    account_hash = os.environ.get('CLOUDFLARE_ACCOUNT_HASH', '').strip()
    
    if not account_id or not api_token or not account_hash:
        print("ERROR: Missing Cloudflare credentials.", file=sys.stderr)
        print("Set these environment variables:", file=sys.stderr)
        print("  CLOUDFLARE_ACCOUNT_ID", file=sys.stderr)
        print("  CLOUDFLARE_API_TOKEN", file=sys.stderr)
        print("  CLOUDFLARE_ACCOUNT_HASH", file=sys.stderr)
        sys.exit(1)
    
    return account_id, api_token, account_hash


def get_direct_upload_url(account_id: str, api_token: str) -> tuple[str, str]:
    """Get a direct upload URL from Cloudflare Images API."""
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v2/direct_upload"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, headers=headers, timeout=30)
    if response.status_code != 200:
        raise Exception(f"Cloudflare API error: {response.status_code} - {response.text}")
    
    result = response.json()
    if not result.get("success"):
        errors = result.get("errors", [])
        error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
        raise Exception(f"Cloudflare error: {error_msg}")
    
    upload_data = result.get("result", {})
    upload_url = upload_data.get("uploadURL", "")
    upload_id = upload_data.get("id", "")
    
    if not upload_url:
        raise Exception("No upload URL received from Cloudflare")
    
    return upload_url, upload_id


def upload_file(file_path: Path, upload_url: str) -> dict:
    """Upload a file to the Cloudflare direct upload URL."""
    with open(file_path, 'rb') as f:
        files = {'file': (file_path.name, f, get_mime_type(file_path))}
        response = requests.post(upload_url, files=files, timeout=120)
    
    if response.status_code != 200:
        raise Exception(f"Upload failed: {response.status_code} - {response.text}")
    
    result = response.json()
    if not result.get("success"):
        errors = result.get("errors", [])
        error_msg = errors[0].get("message", "Upload failed") if errors else "Upload failed"
        raise Exception(error_msg)
    
    return result.get("result", {})


def get_mime_type(file_path: Path) -> str:
    """Get MIME type based on file extension."""
    ext = file_path.suffix.lower()
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.svg': 'image/svg+xml',
        '.bmp': 'image/bmp',
        '.ico': 'image/x-icon',
    }
    return mime_types.get(ext, 'application/octet-stream')


def upload_single_file(file_path: Path, account_id: str, api_token: str, account_hash: str) -> tuple[Path, str, str]:
    """Upload a single file and return (path, url, error)."""
    try:
        upload_url, upload_id = get_direct_upload_url(account_id, api_token)
        result = upload_file(file_path, upload_url)
        
        image_id = result.get("id", upload_id)
        
        variants = result.get("variants", [])
        if variants:
            final_url = variants[0]
        else:
            final_url = f"https://imagedelivery.net/{account_hash}/{image_id}/public"
        
        return (file_path, final_url, None)
    except Exception as e:
        return (file_path, None, str(e))


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <folder_path> [--workers N]", file=sys.stderr)
        print("\nUploads all images in folder to Cloudflare Images.", file=sys.stderr)
        print("\nOptions:", file=sys.stderr)
        print("  --workers N   Number of parallel uploads (default: 4)", file=sys.stderr)
        sys.exit(1)
    
    folder_path = Path(sys.argv[1]).resolve()
    
    workers = 4
    if '--workers' in sys.argv:
        idx = sys.argv.index('--workers')
        if idx + 1 < len(sys.argv):
            workers = int(sys.argv[idx + 1])
    
    if not folder_path.is_dir():
        print(f"ERROR: '{folder_path}' is not a directory", file=sys.stderr)
        sys.exit(1)
    
    env_file = Path.home() / ".mirage" / "config" / "backend.env"
    if env_file.exists():
        load_env_file(env_file)
    else:
        print(f"WARNING: {env_file} not found, using environment variables", file=sys.stderr)
    
    account_id, api_token, account_hash = get_credentials()
    
    image_files = []
    for f in sorted(folder_path.iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
            image_files.append(f)
    
    if not image_files:
        print(f"No image files found in '{folder_path}'", file=sys.stderr)
        print(f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found {len(image_files)} images to upload...", file=sys.stderr)
    print(f"Using {workers} parallel workers", file=sys.stderr)
    print("", file=sys.stderr)
    
    results = []
    errors = []
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(upload_single_file, f, account_id, api_token, account_hash): f
            for f in image_files
        }
        
        for i, future in enumerate(as_completed(futures), 1):
            file_path, url, error = future.result()
            
            if error:
                errors.append((file_path, error))
                print(f"[{i}/{len(image_files)}] FAILED: {file_path.name} - {error}", file=sys.stderr)
            else:
                results.append((file_path, url))
                print(f"[{i}/{len(image_files)}] OK: {file_path.name}", file=sys.stderr)
    
    print("", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Uploaded: {len(results)}/{len(image_files)}", file=sys.stderr)
    if errors:
        print(f"Failed: {len(errors)}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("", file=sys.stderr)
    
    results.sort(key=lambda x: x[0].name)
    
    output_lines = []
    for file_path, url in results:
        line = f"{file_path.name}\t{url}"
        output_lines.append(line)
        print(url)
    
    output_file = folder_path / "upload_results.txt"
    with open(output_file, 'w') as f:
        f.write('\n'.join(output_lines) + '\n')
    
    print("", file=sys.stderr)
    print(f"Results saved to: {output_file}", file=sys.stderr)
    
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()

