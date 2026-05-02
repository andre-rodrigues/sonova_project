# Lead Data Engineer - Technical Assessment

## Time

**2-3 hours.** You are expected to use AI-assisted development tools (GitHub Copilot, Claude Code, Cursor, Codex, or similar). How you use them — and when you override them — is part of the evaluation.

## Scenario

You are joining a medical hearing-device company. The People Analytics team needs a unified, analytics-ready view of employee data currently spread across three source systems. The data is exported nightly as CSV files.

The source data contains sensitive employee information subject to GDPR and local employment law.

## Source Data

```
data/
├── successfactors/          # SAP SuccessFactors — Core HR
│   ├── employees.csv
│   ├── employee_personal.csv
│   ├── employee_contact.csv
│   ├── employee_job.csv
│   ├── employee_compensation.csv
│   ├── departments.csv
│   ├── job_codes.csv
│   └── locations.csv
├── servicenow/              # ServiceNow — HR support tickets
│   ├── tickets.csv
│   ├── ticket_comments.csv
│   └── ticket_categories.csv
└── atoss/                   # ATOSS — Time & attendance
    ├── time_entries.csv
    ├── absence_requests.csv
    └── absence_types.csv
```

Explore the data thoroughly before writing code. There can be data quality issues.

## Requirements

1. Build an ETL pipeline that ingests this data and produces an analytics-ready output.
2. Apply appropriate data governance given the nature of the data.
3. Demonstrate the output works with example queries.
4. Everything must run locally — no cloud environment is provided.

You do not necessarily need to process all 14 tables. Choose what to focus on and explain why.

## Deliverables

Return a zip file or git repository containing:

- Runnable source code
- A README covering: how to run it, your design decisions, what governance you applied, and how you used AI tools (what helped, what you corrected)
- Output files or instructions to generate them
- Example analytical queries and results

## Evaluation Criteria

- **AI tool usage** — effective use and knowing when to intervene
- **Data engineering** — ETL structure, data modelling, data quality handling
- **Data governance** — appropriate for the sensitivity of this data
- **Code quality** — clean, readable, well-organised
- **Pragmatism** — smart trade-offs for a 2-hour window

It's okay not to finish everything. We prefer a well-thought-out partial solution over a rushed complete one.
