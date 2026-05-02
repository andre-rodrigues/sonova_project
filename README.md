# Lead Data Engineer - Technical Assessment

Welcome! Please read **TASK.md** for the full instructions.

## Contents

```
├── TASK.md                          # Your assignment (start here)
├── README.md                        # This file
└── data/
    ├── successfactors/              # SAP SuccessFactors — Core HR
    │   ├── employees.csv            # Employee records (ID, hire date, status)
    │   ├── employee_personal.csv    # PII: name, DOB, gender, national ID
    │   ├── employee_contact.csv     # Contact details (multi-row per employee)
    │   ├── employee_job.csv         # Job history with effective dates
    │   ├── employee_compensation.csv# Salary history
    │   ├── departments.csv          # Department lookup
    │   ├── job_codes.csv            # Job title / family lookup
    │   └── locations.csv            # Office / site lookup
    ├── servicenow/                  # ServiceNow — HR Tickets
    │   ├── tickets.csv              # HR support tickets
    │   ├── ticket_comments.csv      # Journal entries (separate table)
    │   └── ticket_categories.csv    # Category lookup
    └── atoss/                       # ATOSS — Time & Attendance
        ├── time_entries.csv         # Clock in/out records
        ├── absence_requests.csv     # Leave requests
        └── absence_types.csv        # Leave type lookup
```

## Quick Start

1. Read `TASK.md` carefully.
2. Explore the data files — start by understanding how the tables relate across systems.
3. Build your ETL pipeline using your preferred tools.
4. Use AI tools — we want to see how you work with them.
5. Present your solution in the session.

## Requirements

- Python
- No cloud accounts or external services needed — everything runs locally.

Good luck!
