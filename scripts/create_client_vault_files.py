"""
One-time script: Create Dashboard.md and FAQ.md in 2-Areas/Clients/ on Google Drive.
Run locally with your .env.deploy credentials loaded.

Usage:
    source .env.deploy
    export GCP_PROJECT_ID=screenshot-processor-ak
    export DRIVE_VAULT_ROOT_FOLDER_ID=1VKCaMxB639IyfwDHIvZPE4YzhZheTpuq
    python3 scripts/create_client_vault_files.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import drive_ops
from config import VAULT_PATHS, DRIVE_VAULT_ROOT_FOLDER_ID

DASHBOARD_CONTENT = """---
tags: [dashboard, booking]
---

# 📸 Booking Pipeline

## 🔴 Need to Reply
```dataview
TABLE client, platform, shoot_type, date_discussed
FROM "2-Areas/Clients"
WHERE status = "need-to-reply"
SORT last_updated DESC
```

## 🟡 Waiting for Response
```dataview
TABLE client, platform, shoot_type, date_discussed
FROM "2-Areas/Clients"
WHERE status = "waiting"
SORT last_updated DESC
```

## 🟢 Confirmed Shoots
```dataview
TABLE client, platform, shoot_type, date_discussed, location
FROM "2-Areas/Clients"
WHERE status = "confirmed"
SORT date_discussed ASC
```

## ✅ Completed
```dataview
TABLE client, platform, shoot_type, date_discussed
FROM "2-Areas/Clients"
WHERE status = "completed"
SORT last_updated DESC
LIMIT 20
```

## 📊 Stats
```dataview
TABLE length(rows) AS Count
FROM "2-Areas/Clients"
WHERE status != null
GROUP BY status
```
"""

FAQ_CONTENT = """# 📸 Booking FAQ

> This file is read by the screenshot processor to generate suggested replies.
> Fill in YOUR actual info below. The more detail, the better the replies.

## Pricing
- Portrait session (1 hour): €___
- Couple session (1.5 hours): €___
- Family session (2 hours): €___
- Event coverage (4 hours): €___
- Editorial/fashion (half day): €___

## What's Included
- Number of edited photos: ___
- Delivery format: Google Drive / Dropbox / etc.
- Raw files: included / available for +€___

## Availability
- Days available: weekdays / weekends / both
- Preferred times: morning / golden hour / flexible
- Advance booking: ___ days minimum

## Location
- Home city: ___
- Favorite shoot locations: ___
- Travel outside city: +€___ for transport
- Studio available: yes / no

## Turnaround Time
- Standard delivery: ___ business days
- Rush delivery: ___ days for +€___

## Style & Approach
- Shooting style: natural light / studio / mixed
- Editing style: clean / moody / film-look / etc.
- Mood boards: accepted / preferred

## Languages
- Languages you work in: English, Italian, Russian, Greek

## Booking Process
1. ___
2. ___
3. Deposit of ___% to confirm

## Cancellation Policy
- Free cancellation: ___ hours before
- Late cancellation fee: €___
"""


def main():
    print("=== Creating Client Vault Files ===\n")

    # Find or create 2-Areas/Clients folder
    clients_path = VAULT_PATHS["clients"]
    folder_id = drive_ops.find_folder_by_path(clients_path)

    if not folder_id:
        print(f"Creating folder path: {clients_path}")
        parts = clients_path.split("/")
        current = DRIVE_VAULT_ROOT_FOLDER_ID
        for part in parts:
            existing = drive_ops.find_folder_by_path(part, root_folder_id=current)
            if existing:
                current = existing
            else:
                current = drive_ops.create_folder(current, part)
                print(f"  Created: {part}")
        folder_id = current

    print(f"Clients folder ID: {folder_id}\n")

    # Create Dashboard.md
    existing = drive_ops.find_file_by_name("Dashboard.md", folder_id)
    if existing:
        print("Dashboard.md already exists, skipping")
    else:
        file_id = drive_ops.create_md_file(folder_id, "Dashboard.md", DASHBOARD_CONTENT)
        print(f"✅ Created Dashboard.md (id={file_id})")

    # Create FAQ.md
    existing = drive_ops.find_file_by_name("FAQ.md", folder_id)
    if existing:
        print("FAQ.md already exists, skipping")
    else:
        file_id = drive_ops.create_md_file(folder_id, "FAQ.md", FAQ_CONTENT)
        print(f"✅ Created FAQ.md (id={file_id})")

    print("\n=== Done! Check your vault at 2-Areas/Clients/ ===")


if __name__ == "__main__":
    main()
