import secrets
import string
import os
from pathlib import Path

def generate_random_string(length: int = 32) -> str:
    """Generate a secure random string of specified length."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def update_env_file(updates: dict[str, str]):
    """Update the .env file with the provided key-value pairs."""
    env_path = Path(".env")
    lines = []
    
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = f.readlines()
            
    updated_keys = set()
    new_lines = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
            
        if "=" in line:
            key, _ = line.split("=", 1)
            key = key.strip()
            if key in updates:
                new_lines.append(f'{key}="{updates[key]}"\n')
                updated_keys.add(key)
                continue
        
        new_lines.append(line)
        
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f'{key}="{value}"\n')
            
    with open(env_path, "w") as f:
        f.writelines(new_lines)

