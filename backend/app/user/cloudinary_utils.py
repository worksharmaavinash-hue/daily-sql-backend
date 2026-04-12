import hashlib
import hmac
import time
from typing import Dict, Any

def generate_cloudinary_signature(params: Dict[str, Any], api_secret: str) -> str:
    """
    Generates a Cloudinary signature for client-side uploads.
    Params should NOT include file, api_key, resource_type, or signature.
    """
    # 1. Sort parameters alphabetically
    sorted_params = []
    for key in sorted(params.keys()):
        sorted_params.append(f"{key}={params[key]}")
    
    # 2. Join with & as separator (Wait, Cloudinary uses & for some things, but signing string is often key=val pairs joined by &)
    # Actually, Cloudinary signing string is: key1=val1&key2=val2...secret
    signing_string = "&".join(sorted_params) + api_secret
    
    # 3. Use SHA-1 or SHA-256 (Cloudinary supports both, default for v1 is SHA-1)
    return hashlib.sha1(signing_string.encode('utf-8')).hexdigest()

def get_upload_params(public_id: str, api_secret: str):
    """
    Returns signed parameters for an image upload.
    """
    timestamp = int(time.time())
    params = {
        "timestamp": timestamp,
        "public_id": public_id,
        "folder": "profile_photos"
    }
    
    signature = generate_cloudinary_signature(params, api_secret)
    
    return {
        "params": params,
        "signature": signature
    }
