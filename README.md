# Equity PnL Monitor

This project has two modes:

1. Local Python web app: `app.py`
2. Shared Streamlit Cloud app: `streamlit_app.py`

The shared Streamlit version is designed for this workflow:

```text
Users open your website
  -> enter a viewer/editor/admin password
  -> viewers can only read
  -> editors/admins can input trades on the website
  -> trades are written to Google Sheets through Google Apps Script
  -> PnL and holdings refresh from the shared trade ledger
```

## Streamlit Files

- `streamlit_app.py`: cloud app entrypoint.
- `requirements.txt`: packages installed by Streamlit Cloud.
- `.streamlit/secrets.toml.example`: template for Streamlit secrets.
- `apps_script_code.gs`: Google Apps Script web app code.
- Google Sheet tab `Trades`: shared transaction ledger.
- Google Sheet tab `Audit Log`: who changed what and when.

Do not commit real secrets, Excel files, or trade data to GitHub.

## Google Sheet Setup

Use this Google Sheet:

```text
1a9ahW9brvGS6B2QMDgUwRQmLRXiHDKecX4G-oZ8acFQ
```

Create two tabs:

```text
Trades
Audit Log
```

The Apps Script will create headers automatically if the tabs are empty.

Recommended `Trades` columns:

```text
id,date,side,symbol,fmp_symbol,name,quantity,price,currency,fee,note,source,created_by,created_at
```

Recommended `Audit Log` columns:

```text
timestamp,user,action,symbol,side,quantity,price,note
```

## Google Apps Script Setup

This is the recommended free setup. It does not require Google Cloud service accounts.

1. Open the Google Sheet.
2. Go to Extensions > Apps Script.
3. Paste the contents of `apps_script_code.gs`.
4. In Apps Script, go to Project Settings > Script properties.
5. Add a property:

```text
APP_TOKEN = make-a-long-random-token
```

6. Click Deploy > New deployment.
7. Type: Web app.
8. Execute as: Me.
9. Who has access: Anyone.
10. Deploy and copy the Web app URL.

Put that Web app URL and the same `APP_TOKEN` into Streamlit secrets:

```toml
[apps_script]
url = "YOUR_GOOGLE_APPS_SCRIPT_WEB_APP_URL"
token = "make-a-long-random-token"
```

## Streamlit Cloud Deployment

1. Push this folder to a private GitHub repo.
2. Open Streamlit Community Cloud.
3. Create app from the repo.
4. Main file path:

```text
streamlit_app.py
```

5. Paste secrets from `.streamlit/secrets.toml.example` into App settings > Secrets.
6. Deploy.

## Local Web App

The original local app still works:

```powershell
cd "C:\Users\Admin\Documents\New project\portfolio_monitor"
$env:PORT="8772"
$env:HOST="127.0.0.1"
& "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" app.py
```

Then open:

```text
http://127.0.0.1:8772
```

## Local Streamlit Test

Install requirements, then run:

```powershell
pip install -r requirements.txt
streamlit run streamlit_app.py
```

If Google Sheets secrets are not configured locally, the Streamlit app falls back to local Excel plus `data/streamlit_trades.json`.
