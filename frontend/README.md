Email Generator

A full-stack app that scrapes a business website and generates ready-to-send HTML promotional emails, using an LLM to fill in copy and match the site's own visual identity.

Features
Natural-language input — a single command like "generate a discount email from this website: url" captures both the target site and the desired email type
Automated scraping — Playwright extracts page text, headings, meta description, and candidate images (filtered by size, with Open Graph image prioritized)
Design extraction — pulls the site's actual background/text/accent colors and layout density directly from computed styles, so generated emails visually match the source brand without any manual styling input
Flexible generation — supports free-form topic focus (e.g. "ready to wear essentials"), custom image counts, and length preferences (short/medium/long)
Fact-checking loop — a critic pass checks each draft against the scraped business profile and flags/rejects any invented discounts, products, or claims not actually present on the site, regenerating up to 3 times if needed
Editable output — a revision endpoint lets you request specific changes to a generated email while preserving verified facts and existing styling
Tech Stack
Scraping: Playwright (Python)
Backend: FastAPI
LLM: Groq (openai/gpt-oss-120b)
Frontend: React (Vite) + axios
Setup
Clone the repo and install backend dependencies
Add your Groq API key to a .env file (GROQ_API_KEY=...)
Run the FastAPI backend and the React frontend
Enter a command like "generate a welcome email from https://example.com" and let it scrape, profile, and generate
