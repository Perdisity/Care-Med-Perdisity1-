# CareMed

Purpose of the Project

The purpose of this project is to develop a cybersecurity-integrated web-based management system for CareMed, a medical supply enterprise that currently relies on manual business operations. The system aims to automate essential processes such as inventory management, sales and rental transactions, customer record management, and report generation to improve operational efficiency and accuracy.

In addition, the project focuses on integrating cybersecurity mechanisms such as user authentication, role-based access control, and activity monitoring to ensure the protection of sensitive business data and prevent unauthorized access. By transitioning from manual processes to a secure digital infrastructure, the project seeks to enhance productivity, reduce human errors, improve data management, and provide a more reliable service experience for both administrators and customers.


It looks like it was simply cut off when you copied or previewed the text block earlier. Here is the complete, unbroken markdown containing sections **1, 2, and 3** ready to be copied directly into your `README.md` file:


# CareMed
---

## Automated Recurring Invoice System & Production Guide

To handle open-duration equipment rentals efficiently in a real-world production environment, CareMed includes a built-in automated billing module that generates subsequent monthly invoices prior to cycle expiration.

### 1. System Architecture & Components
* **Model Level Extension (`models/product.py`):** 
  * The `Rental` model includes the `is_open_duration` boolean flag to track ongoing, open-ended rentals.
  * Helper methods (`get_latest_invoice()` and `generate_next_monthly_invoice()`) automatically calculate service periods using `relativedelta` and create unpaid monthly invoices while extending expected return dates dynamically.
* **Standalone Execution Script (`generate_monthly_invoices.py`):** 
  * Located in the root application directory, this script instantiates the Flask application context, queries active open-duration rentals, checks if the latest invoice's service period end date is within a 3-day window, and commits new recurring invoices directly to the database.

### 2. Manual Testing Guide
Administrators or system maintainers can manually test or execute the background invoice generation script at any time via the server terminal:
```bash
python generate_monthly_invoices.py

```

* *Note:* The script outputs the timestamp and the total number of successfully generated recurring invoices.

### 3. Long-Term Production Deployment & Automation

To ensure the system runs autonomously on a live production server without manual intervention or third-party web dependencies, pair the script with your operating system's native scheduler:

**Linux / Ubuntu Server (Cron Job):**

Open the crontab configuration editor in server:

```bash
crontab -e

```

Add the following rule to execute the script daily at midnight (`0 0 * * *`), directing output to a local log file:

```bash
0 0 * * * /home/username/CareMed-App/venv/bin/python /home/username/CareMed-App/generate_invoices.py >> /home/username/CareMed-App/logs/caremed_invoices.log 2>&1



```
Step 4: Verify Your Setup
To ensure the system successfully registered your automated schedule, run:

Bash
crontab -l
This will list all active cron jobs for the current user.

Anatomy of the Schedule (0 0 * * *):

First 0: Minute (0th minute)

Second 0: Hour (0th hour / Midnight)

First *: Day of the month (Every day)

Second *: Month (Every month)

Third *: Day of the week (Every day of the week)

This means the script will execute automatically every single day at 12:00 AM.

**Windows Environment (Task Scheduler):**

* Open **Task Scheduler** and create a Basic Task named **CareMed Monthly Invoices**.
* Set the trigger to **Daily** running at 12:00 AM.
* Set the action to **Start a program**, pointing to your virtual environment's `python.exe` with `run_invoice_cron.py` as the argument and your project root folder as the "Start in" path.

---

## Running Automated Tests

To run the automated business-rule and security test suite:
```bash
pytest -q
<!-- telemetry: 2026-10-30T07:03:15Z id: 29236140-9050-471c-98a8-bcf2009d392a -->
