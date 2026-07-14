# LinkedIn Auto Connector

Automates sending personalized LinkedIn connection requests based on your search criteria — keyword, location, connection degree, and more.

> **Original credits:** [Ahmed Mujtaba](https://www.linkedin.com/in/creative-programmer/)

---

## What It Does

- Searches LinkedIn people by keyword, location, and connection degree
- Sends connection requests automatically (up to your set limit)
- Attaches a personalized note using the recipient's first name
- Logs in via cookie (`li_at`) to avoid detection

---

## Prerequisites

- Python 3.8+
- Google Chrome installed
- A LinkedIn account

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/bhuvanendra1520/Linkedin-Auto-Connector.git
cd Linkedin-Auto-Connector
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Get your LinkedIn `li_at` cookie

1. Open Chrome and log in to [linkedin.com](https://www.linkedin.com)
2. Press `F12` to open Developer Tools
3. Go to **Application** → **Cookies** → `https://www.linkedin.com`
4. Find the `li_at` cookie and copy its value

### 4. Configure `input_config.ini`

Copy the example file and edit it with your preferences:

```bash
cp input_config.example.ini input_config.ini
```

```ini
[SearchCriteria]
connection_degree = 2nd        # 1st, 2nd, or 3rd
keyword = Recruiter            # Job title or keyword to search
location = United States       # Filter by location
actively_hiring =              # Leave blank, or use "Any job title" to filter hiring managers
limit = 100                    # Max number of requests to send

[LinkedIn]
li_at = YOUR_LI_AT_COOKIE_HERE

[Messages]
include_note = True            # True = attach a note to each request
connection_message = Hi {name}, I'm an AI/ML Engineer exploring new roles. Let's connect!
message_letter =               # For 1st-degree: direct message (leave blank if not needed)
```

> **Tip:** Use `{name}` in `connection_message` — it gets replaced with the person's first name automatically.

### 5. Run it

```bash
python main.py
```

---

## Configuration Reference

| Field | Options | Description |
|---|---|---|
| `connection_degree` | `1st`, `2nd`, `3rd` | Degree of connection to target |
| `keyword` | Any string | Search term (e.g. `Recruiter`, `Software Engineer`) |
| `location` | Any string | Location filter (e.g. `United States`) |
| `actively_hiring` | blank or `Any job title` | Filter for people actively posting jobs |
| `limit` | Number | Max connection requests to send per run |
| `include_note` | `True` / `False` | Whether to attach a note to requests |
| `connection_message` | Text with `{name}` | Note sent with 2nd/3rd-degree requests |
| `message_letter` | Text | Direct message for 1st-degree connections |

---

## Common Issues

**Nothing gets sent / script skips everyone**
- If `connection_degree = 1st`, set `message_letter` with a message, or switch to `2nd`
- 1st-degree profiles show a "Message" button, not "Connect"

**Name shows as "Connection1" instead of real name**
- LinkedIn DOM changes break XPath selectors — the script uses a JS fallback to handle this

**Login fails**
- Your `li_at` cookie may have expired — refresh it from DevTools (expires every few weeks)

**`actively_hiring = True` doesn't work**
- Use `Any job title` or leave it blank — `True` is not a valid value

---

## Security Warning

- **Never commit `input_config.ini` or `setup.ini`** — they contain your cookie and credentials
- Both files are listed in `.gitignore` by default

---

## Contributing

1. Fork the repo
2. Create a branch: `git checkout -b feature/my-feature`
3. Commit and push your changes
4. Open a pull request
