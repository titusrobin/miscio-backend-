# Fixed SendGrid configuration checker
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

def check_sendgrid_config():
    """Check actual SendGrid configuration via API"""
    
    api_key = os.getenv('SENDGRID_API_KEY')
    if not api_key:
        print("❌ SENDGRID_API_KEY not found in environment")
        return
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    try:
        print("=== CHECKING SENDGRID INBOUND PARSE CONFIG ===")
        
        response = requests.get(
            'https://api.sendgrid.com/v3/user/webhooks/parse/settings',
            headers=headers
        )
        
        print(f"API Response Status: {response.status_code}")
        print(f"API Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            try:
                config_data = response.json()
                print(f"Raw API Response: {json.dumps(config_data, indent=2)}")
                
                # Handle different response formats
                if isinstance(config_data, list):
                    configs = config_data
                elif isinstance(config_data, dict) and 'result' in config_data:
                    configs = config_data['result']
                else:
                    configs = [config_data] if config_data else []
                
                print(f"\nFound {len(configs)} inbound parse configurations:")
                
                configured_domains = []
                for i, config in enumerate(configs):
                    if isinstance(config, dict):
                        hostname = config.get('hostname', 'N/A')
                        url = config.get('url', 'N/A')
                        spam_check = config.get('spam_check', False)
                        send_raw = config.get('send_raw', False)
                        
                        print(f"\nConfig {i+1}:")
                        print(f"  Host: {hostname}")
                        print(f"  URL: {url}")
                        print(f"  Spam Check: {spam_check}")
                        print(f"  Send Raw: {send_raw}")
                        
                        configured_domains.append(hostname)
                    else:
                        print(f"Config {i+1}: {config}")
                
                # Check for your specific domain
                target_domain = "em1650.miscioapp.com"
                domain_configured = target_domain in configured_domains
                
                print(f"\n=== DOMAIN CHECK ===")
                print(f"Looking for domain: {target_domain}")
                print(f"Configured domains: {configured_domains}")
                print(f"Domain configured: {'✅ YES' if domain_configured else '❌ NO'}")
                
                if domain_configured:
                    print(f"\n✅ SUCCESS: {target_domain} is properly configured!")
                    print("Your webhook should receive emails sent to robin@em1650.miscioapp.com")
                else:
                    print(f"\n❌ ISSUE: {target_domain} is NOT configured")
                    print("You need to add this domain in SendGrid Inbound Parse settings")
                
            except json.JSONDecodeError as e:
                print(f"❌ Failed to parse JSON response: {e}")
                print(f"Raw response: {response.text}")
                
        else:
            print(f"❌ API Error: {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

def check_mx_records():
    """Check MX records for the domain"""
    import subprocess
    
    domain = "em1650.miscioapp.com"
    print(f"\n=== CHECKING MX RECORDS FOR {domain} ===")
    
    try:
        result = subprocess.run(['nslookup', '-type=MX', domain], 
                              capture_output=True, text=True, timeout=10)
        
        print("nslookup output:")
        print(result.stdout)
        
        if "mx.sendgrid.net" in result.stdout.lower():
            print("✅ MX record points to SendGrid")
        else:
            print("❌ MX record may not be configured for SendGrid")
            print("You may need to add: em1650.miscioapp.com MX 10 mx.sendgrid.net")
            
    except subprocess.TimeoutExpired:
        print("❌ nslookup timed out")
    except FileNotFoundError:
        print("❌ nslookup command not found (Windows users: use 'nslookup -type=MX em1650.miscioapp.com')")
    except Exception as e:
        print(f"❌ Error checking MX records: {e}")

if __name__ == "__main__":
    check_sendgrid_config()
    check_mx_records()
    
    print("\n=== NEXT STEPS ===")
    print("1. If domain is configured ✅ and MX records are correct ✅: Test with real email")
    print("2. If domain is missing ❌: Add em1650.miscioapp.com to SendGrid Inbound Parse")
    print("3. If MX records are wrong ❌: Add MX record in your DNS settings")
    print("4. Test by sending a campaign and replying to it")