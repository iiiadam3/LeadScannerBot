# 🚀 Automated Reddit Lead Scanner

A Python-based automation tool designed to autonomously scout, filter, and deliver high-quality freelance leads from Reddit directly to an email inbox.

## 📖 The Motivation
Searching for freelance gigs on platforms like Reddit involves sifting through hundreds of irrelevant posts. I built this tool to automate the prospecting phase. By the time I wake up, the script has already scanned targeted subreddits, filtered out the noise, and emailed me a clean CSV of potential clients.

## ✨ Key Features
* **Smart 2D Filtering:** Moves beyond basic keyword searches. It requires a match in both **Intent** (e.g., "looking for a developer", "willing to pay") and **Context** (e.g., "Wordpress", "Shopify"), while strictly avoiding **Negative** keywords (e.g., "hire me", "tutorial").
* **Bypassing Anti-Scraping Protocols:** Successfully navigated Reddit's 403 API blocks (Responsible Builder Policy) by architecting a local automation pipeline instead of relying on easily blocked cloud servers.
* **Zero-Touch Execution:** Fully automated using a batch script and Windows Task Scheduler to run silently in the background daily.
* **Automated Reporting:** Generates a pandas DataFrame, converts it to a CSV, and securely emails it using the `smtplib` library.

## 🛠️ Tech Stack
* **Language:** Python 3
* **Libraries:** `pandas` (Data manipulation), `requests` (HTTP client), `smtplib` / `email` (SMTP protocol)
* **Automation:** Windows Task Scheduler, Batch Scripting (.bat)

## 💡 What I Learned
This project was an excellent exercise in building a complete Data Pipeline (ETL) and handling real-world network challenges. Dealing with Reddit's restrictive API taught me how to pivot architectures quickly and build resilient, locally-hosted automation solutions.