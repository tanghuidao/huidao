"""Remove misplaced email verification fields from non-User models."""
import sys
sys.path.insert(0, '/app')

filepath = '/app/app/models.py'

with open(filepath, 'r') as f:
    lines = f.readlines()

# Remove the 4B email verification block from specific models
# We need to remove lines that are inside:
#   Alert class (before Watchlist)
#   AgentTask class (before DiscoveredSource)
#   DiscoveredSource class (before FactCheck)
#   Payment class (before ApiKey)
# But KEEP the block inside User class

# Strategy: find each "# 4B-1" comment and remove the 4 lines (comment + 3 fields)
# EXCEPT when it's inside the User class

# First, find the User class start line
user_class_line = None
for i, line in enumerate(lines):
    if 'class User(Base):' in line:
        user_class_line = i
        break

print(f"User class starts at line {user_class_line + 1}")

# Find all 4B-1 blocks
blocks_to_remove = []
for i, line in enumerate(lines):
    if '# 4B-1: Email verification fields' in line:
        if i < user_class_line or i > user_class_line + 30:
            # This is NOT inside User class
            blocks_to_remove.append(i)
            print(f"  Will remove block at line {i + 1}: {line.strip()}")

# Remove blocks (in reverse order to preserve line numbers)
removed = 0
for start_line in reversed(blocks_to_remove):
    # Remove 4 lines: comment + email_verified + verification_token + verification_sent_at
    del lines[start_line:start_line + 4]
    removed += 4

with open(filepath, 'w') as f:
    f.writelines(lines)

print(f"\nRemoved {removed} lines ({removed // 4} blocks)")
print("Email verification fields now only exist in User model")
