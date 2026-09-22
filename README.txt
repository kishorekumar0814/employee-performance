EMPLOYEE PERFORMANCE ROLE-BASED APP - CORRECTED VERSION

WHAT WAS FIXED IN THIS VERSION
1. Model never predicted "Poor" or "Excellent" (25% accuracy overall).
   -> Retrained employee_performance_model.pkl on employee_performance_
      dataset_enhanced.xlsx with a proper stratified train/test split.
      Now 54% accuracy with all 5 classes represented (see train_model.py
      for the training code and its printed classification report).
2. "Database is locked" errors.
   -> add_employee() and predict() opened a SQLite connection but never
      closed it if the request failed partway through (bad input, etc).
      Both now use try/finally so the connection always closes.
3. Employees from one company showing up under a different company.
   -> Verified: the company_id scoping logic itself was already correct
      in every query. This was almost certainly caused by an old
      performance.db (with pre-multi-tenant or stale data) being
      committed to git and redeployed. Added .gitignore so the database
      is never committed - it should always be created fresh by the app.

RUNNING LOCALLY
1. Keep these together in one folder:
   app.py, requirements.txt, employee_performance_model.pkl,
   selected_features.pkl, templates/, static/
2. pip install -r requirements.txt
3. python app.py
4. Open http://127.0.0.1:5000
   (Only reachable from this same computer - see "hosting" below for
   sharing with others.)

DEFAULT LOGINS (created automatically on first run)
  HR:    hr / hr123
  ADMIN: admin / admin123
Sign up new HR/Admin accounts for new companies from the Sign Up page -
each company you enter there gets fully separate data.

HOSTING ON RENDER (or similar)
1. Push this whole folder to a GitHub repo.
   IMPORTANT: do NOT commit performance.db - .gitignore already excludes
   it, but double check with: git status
   If performance.db shows as tracked, run: git rm --cached performance.db
2. On Render: New -> Web Service -> connect the repo.
   Build command:  pip install -r requirements.txt
   Start command:  (already set via Procfile: gunicorn app:app)
3. Deploy. Every fresh deploy creates a brand-new, empty performance.db -
   this is expected and is what keeps companies' data clean.
4. NOTE: Render's free tier has no persistent disk by default, meaning
   performance.db can reset when the service restarts/redeploys/sleeps
   from inactivity. Fine for a demo; for data that must survive long-
   term, either attach a Render persistent disk to this folder, or
   migrate to a hosted database (e.g. Render's free PostgreSQL).

TESTING IT WORKS
- Sign up two different companies with two different usernames, add an
  employee under each, and confirm each HR/Admin only ever sees their
  own company's employees.
- On the Predict page, try satisfaction_score values of 1, 4, 6, 8, 10
  (keep other fields moderate) - these should trend from Poor through
  Excellent, since satisfaction_score is the strongest single driver
  in this dataset.

KNOWN LIMITATION (for your report, not a bug)
satisfaction_score alone accounts for ~65% of the model's decision -
the other 9 input features are only weakly correlated with the actual
outcome in this dataset. 54% accuracy / 0.52 macro-F1 across 5 close
ordinal classes is close to the ceiling achievable with these specific
features. To push accuracy meaningfully higher, the dataset would need
additional features that actually correlate with performance (manager
ratings, KPI scores, peer feedback, etc.), not further model tuning.
