#!/usr/bin/env python3
"""
regenerate_oauth2_token.py - Generate OAuth 2.0 token using OAuth 1.0a credentials
"""

import os
import sys
import time
import logging
import requests
import hmac
import hashlib
import base64
import urllib.parse
import uuid
from datetime import datetime
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    filename='token_refresh.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Add a console handler for debugging
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logging.getLogger().addHandler(console_handler)

def update_env_file(updates, file_path='.env'):
    """Update the .env file with new values without adding quotation marks"""
    try:
        # First read the original file
        with open(file_path, 'r') as file:
            lines = file.readlines()
        
        # Update values
        updated_keys = set()
        updated_lines = []
        
        for line in lines:
            original_line = line
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                updated_lines.append(original_line)
                continue
            
            # Check for key=value pairs
            if '=' in line:
                key, _ = line.split('=', 1)
                key = key.strip()
                
                if key in updates:
                    updated_lines.append(f"{key}={updates[key]}\n")
                    updated_keys.add(key)
                    logging.info(f"Updated {key} in .env file")
                else:
                    updated_lines.append(original_line)
            else:
                updated_lines.append(original_line)
        
        # Add any keys that weren't found
        for key in updates:
            if key not in updated_keys:
                updated_lines.append(f"{key}={updates[key]}\n")
                logging.info(f"Added new key {key} to .env file")
        
        # Write updated file
        with open(file_path, 'w') as file:
            file.writelines(updated_lines)
        
        logging.info("Successfully updated .env file")
        return True
    
    except Exception as e:
        logging.error(f"Error updating .env file: {e}")
        return False

def generate_oauth1_signature(method, url, params, consumer_secret, token_secret):
    """Generate OAuth 1.0a signature"""
    # Create parameter string
    param_string = '&'.join([f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in sorted(params.items())])
    
    # Create signature base string
    signature_base = f"{method}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(param_string, safe='')}"
    
    # Create signing key
    signing_key = f"{urllib.parse.quote(consumer_secret, safe='')}&{urllib.parse.quote(token_secret, safe='')}"
    
    # Generate signature
    signature = base64.b64encode(
        hmac.new(
            signing_key.encode('utf-8'),
            signature_base.encode('utf-8'),
            hashlib.sha1
        ).digest()
    ).decode('utf-8')
    
    return signature

def get_oauth1_header(url, method='GET'):
    """Generate OAuth 1.0a header using credentials from .env file"""
    # Load credentials
    load_dotenv()
    consumer_key = os.getenv('TWITTER_API_KEY')
    consumer_secret = os.getenv('TWITTER_API_SECRET')
    token = os.getenv('TWITTER_ACCESS_TOKEN')
    token_secret = os.getenv('TWITTER_ACCESS_SECRET')
    
    # Generate OAuth parameters
    oauth_params = {
        'oauth_consumer_key': consumer_key,
        'oauth_nonce': uuid.uuid4().hex,
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': str(int(time.time())),
        'oauth_token': token,
        'oauth_version': '1.0'
    }
    
    # Generate signature
    oauth_params['oauth_signature'] = generate_oauth1_signature(
        method, url, oauth_params, consumer_secret, token_secret
    )
    
    # Create Authorization header
    auth_header = 'OAuth ' + ', '.join([
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"' 
        for k, v in oauth_params.items()
    ])
    
    return auth_header

def get_bearer_token():
    """Get app-only bearer token using OAuth 1.0a credentials"""
    logging.info("Attempting to get bearer token using OAuth 1.0a credentials")
    print("Attempting to get bearer token using OAuth 1.0a credentials...")
    
    # Load credentials
    load_dotenv()
    consumer_key = os.getenv('TWITTER_API_KEY')
    consumer_secret = os.getenv('TWITTER_API_SECRET')
    
    logging.debug(f"Using API key: {consumer_key[:5]}...{consumer_key[-5:] if consumer_key else 'None'}")
    
    if not consumer_key or not consumer_secret:
        logging.error("Missing TWITTER_API_KEY or TWITTER_API_SECRET in .env file")
        print("Error: Missing Twitter API credentials in .env file")
        return None
    
    # Create bearer token credentials (using OAuth 2.0 client credentials flow)
    bearer_token_creds = f"{urllib.parse.quote(consumer_key)}:{urllib.parse.quote(consumer_secret)}"
    encoded_bearer_creds = base64.b64encode(bearer_token_creds.encode('utf-8')).decode('utf-8')
    
    headers = {
        'Authorization': f"Basic {encoded_bearer_creds}",
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
    }
    
    data = "grant_type=client_credentials"
    
    try:
        logging.debug(f"Making OAuth2 token request to https://api.twitter.com/oauth2/token")
        response = requests.post(
            'https://api.twitter.com/oauth2/token',
            headers=headers,
            data=data
        )
        
        if response.status_code == 200:
            token_data = response.json()
            token = token_data.get('access_token')
            logging.info(f"Successfully obtained bearer token: {token[:10]}...{token[-10:] if token else 'None'}")
            print("Successfully obtained bearer token")
            return token
        else:
            logging.error(f"Failed to get bearer token: {response.status_code} - {response.text}")
            print(f"Error: Failed to get bearer token (HTTP {response.status_code})")
            print(f"Response: {response.text}")
            return None
    
    except Exception as e:
        logging.error(f"Exception during bearer token request: {e}")
        print(f"Error: {e}")
        return None

def verify_token(bearer_token):
    """Verify the bearer token works by making a test request"""
    if not bearer_token:
        return False
    
    logging.info("Verifying bearer token with a test request")
    print("Verifying bearer token with a test request...")
    
    headers = {
        'Authorization': f"Bearer {bearer_token}"
    }
    
    try:
        # Try to get Twitter API rate limit status as a simple test
        logging.debug("Checking rate limit status as token verification")
        response = requests.get(
            'https://api.twitter.com/1.1/application/rate_limit_status.json',
            headers=headers
        )
        
        if response.status_code == 200:
            # Log some of the available endpoints to confirm what we have access to
            rate_limits = response.json()
            available_endpoints = []
            
            # Check a few important endpoints and their remaining calls
            resources = rate_limits.get('resources', {})
            
            # Check search endpoints
            if 'search' in resources:
                search_limits = resources['search'].get('/search/tweets', {})
                remaining = search_limits.get('remaining', 0)
                logging.info(f"Search API access: {remaining} calls remaining")
                available_endpoints.append('search')
            
            # Check user endpoints
            if 'users' in resources:
                users_limits = resources['users'].get('/users/lookup', {})
                remaining = users_limits.get('remaining', 0)
                logging.info(f"Users API access: {remaining} calls remaining")
                available_endpoints.append('users')
            
            # Check statuses endpoints
            if 'statuses' in resources:
                statuses_limits = resources['statuses'].get('/statuses/user_timeline', {})
                remaining = statuses_limits.get('remaining', 0)
                logging.info(f"Statuses API access: {remaining} calls remaining")
                available_endpoints.append('statuses')
            
            logging.info(f"Bearer token successfully verified with access to: {', '.join(available_endpoints)}")
            print(f"Bearer token successfully verified with access to: {', '.join(available_endpoints)}")
            return True
        else:
            logging.error(f"Bearer token verification failed: {response.status_code} - {response.text}")
            print(f"Error: Bearer token verification failed (HTTP {response.status_code})")
            return False
    
    except Exception as e:
        logging.error(f"Exception during token verification: {e}")
        print(f"Error: {e}")
        return False

def main():
    """Main function to generate and update OAuth 2.0 token"""
    start_time = time.time()
    logging.info("----- Starting OAuth 2.0 token generation process -----")
    print("Starting OAuth 2.0 token generation process...")
    
    # Get bearer token
    bearer_token = get_bearer_token()
    
    if not bearer_token:
        logging.error("Failed to obtain bearer token")
        print("Failed to obtain bearer token. Check token_refresh.log for details.")
        return False
    
    # Verify the token works
    if not verify_token(bearer_token):
        logging.error("Bearer token verification failed")
        print("Bearer token verification failed. Check token_refresh.log for details.")
        return False
    
    # Set expiry time (7 days from now)
    # Note: Twitter app-only bearer tokens typically last longer than 2 hours,
    # but we log the exact time for reference
    expiry_time = time.time() + (7 * 24 * 60 * 60)
    expiry_datetime = datetime.fromtimestamp(expiry_time).strftime('%Y-%m-%d %H:%M:%S')
    
    # Update .env file
    updates = {
        'OAUTH_2_ACCESS_TOKEN': bearer_token,
        'TWITTER_BEARER_TOKEN': bearer_token,
        'TWITTER_TOKEN_EXPIRY': str(expiry_time)
    }
    
    success = update_env_file(updates)
    
    if success:
        total_time = time.time() - start_time
        logging.info(f"Successfully updated tokens in .env file (took {total_time:.2f} seconds)")
        logging.info(f"Token set to expire on: {expiry_datetime}")
        print("Successfully updated OAuth 2.0 tokens in .env file")
        print(f"Token expires on: {expiry_datetime}")
        return True
    else:
        logging.error("Failed to update .env file")
        print("Failed to update .env file. Check token_refresh.log for details.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)