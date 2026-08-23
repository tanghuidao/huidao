"""Fix entity classification - add missing entities to TRACKED_ORGANIZATIONS."""
import sys
sys.path.insert(0, '/app')

filepath = '/app/app/services/tracker.py'

with open(filepath, 'r') as f:
    content = f.read()

# Add new entries before the closing brace of TRACKED_ORGANIZATIONS
old_block = '''    "Fetch.ai": {"category": "crypto", "type": "project"},
}'''

new_block = '''    "Fetch.ai": {"category": "crypto", "type": "project"},
    "Near": {"category": "crypto", "type": "project"},
    "Near Protocol": {"category": "crypto", "type": "project"},
    "Render": {"category": "ai", "type": "project"},
    "Akash": {"category": "ai", "type": "project"},
    "Gensyn": {"category": "ai", "type": "project"},
    "Ritual": {"category": "ai", "type": "project"},
    "Circle": {"category": "crypto", "type": "company"},
    "Tether": {"category": "crypto", "type": "company"},
    "Meta": {"category": "ai", "type": "company"},
    "CFTC": {"category": "regulator", "type": "government"},
    "ESMA": {"category": "regulator", "type": "government"},
}'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(filepath, 'w') as f:
        f.write(content)
    print("Added missing entities to TRACKED_ORGANIZATIONS")
else:
    print("ERROR: Could not find the insertion point")
    # Try to find what's actually there
    if 'Fetch.ai' in content:
        print("Fetch.ai found but block doesn't match exactly")
        idx = content.find('Fetch.ai')
        print(f"Context: ...{content[idx:idx+100]}...")
    else:
        print("Fetch.ai not found in file")
