import os
import time
import requests
import sqlite3
from openai import OpenAI
from datetime import datetime, timezone
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

openai_api_key = os.getenv('OPENAI_API_KEY')
substack_urls = os.getenv('SUBSTACK_URLS')

if not openai_api_key or not substack_urls:
    raise ValueError("Please set the OPENAI_API_KEY and SUBSTACK_URLS environment variables.")

substack_urls = substack_urls.split(',')
client = OpenAI(api_key=openai_api_key)

conn = sqlite3.connect('articles.db')
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY,
        url TEXT UNIQUE
    )
''')
conn.commit()

def article_exists(url):
    """Check if an article already exists in the database by URL."""
    cursor.execute("SELECT 1 FROM articles WHERE url = ?", (url,))
    return cursor.fetchone() is not None

def save_article(url):
    """Save an article to the database."""
    cursor.execute("INSERT INTO articles (url) VALUES (?)", (url,))
    conn.commit()

def fetch_archive(substack_url, cookie=None):
    archive_url = urljoin(substack_url, 'api/v1/archive')
    headers = {'Cookie': f'substack.sid={cookie}'} if cookie else {}
    offset = 0
    limit = 50
    all_posts = []

    while True:
        params = {'offset': offset, 'limit': limit}
        response = requests.get(archive_url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"Failed to retrieve the archive. Status code: {response.status_code}")
            break

        posts = response.json()
        if not posts:
            break

        for post in posts:
            all_posts.append(post)

        if len(all_posts) >= limit:
            break

        offset += limit
        time.sleep(1)

    return all_posts

def fetch_post_content(substack_url, slug, cookie=None):
    post_url = urljoin(substack_url, f'api/v1/posts/{slug}')
    headers = {'Cookie': f'substack.sid={cookie}'} if cookie else {}
    response = requests.get(post_url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to retrieve the post. Status code: {response.status_code}")
        return None

    return response.json()

def summarize_text(text) -> str:
    try:
        response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Provide a detailed summary of the following economics article for a technical reader, preserving all key concepts and ideas, including any images or links. Condense the text to make it faster to read without omitting essential information. Use Markdown formatting."},
            {"role": "user", "content": text}
        ])
        return response.choices[0].message.content
    except Exception as e:
        print(f"An error occurred during summarization: {e}")
        return "Summary not available."

def summarize_latest_articles(substack_urls, output_type='md', dest_folder='.', cookie=None):
    summaries = []

    # Loop over each Substack URL
    for substack_url in substack_urls:
        posts = fetch_archive(substack_url, cookie)

        for post in posts:
            slug = post['slug']
            url = urljoin(substack_url, f'p/{slug}')
            title = post['title']
            date = post['post_date']

            if article_exists(url):
                print(f"Article '{title}' from {substack_url} already exists in the database. Skipping.")
                continue

            print(f"Fetching content for post: {slug} from {substack_url}")
            post_content = fetch_post_content(substack_url, slug, cookie)
            if post_content and 'description' in post_content:
                print("Summarizing article...")
                summary = summarize_text(post_content['description'])
                summaries.append({
                    'url': url,
                    'summary': summary,
                    'date': date,
                    'title': title,
                    'source': substack_url
                })

                save_article(url)
                time.sleep(1)
            else:
                print("No content available")

    # Write summaries to output files
    for summary in summaries:
        # Use the source URL as part of the filename for easy identification
        source_name = summary['source'].replace("https://", "").replace(".", "_").replace("/", "_")
        filename = os.path.join(dest_folder, f"{source_name}_{summary['title'].replace(' ', '_')}.{output_type}")
        
        with open(filename, 'w', encoding='utf-8') as f:
            if output_type == 'md':
                f.write(f"# {summary['title']}\n\n")
                f.write(f"**Date:** {summary['date']}\n\n")
                f.write(f"**Source:** {summary['url']}\n\n")
                f.write(summary['summary'])
            else:
                f.write(f"<h1>{summary['title']}</h1>\n")
                f.write(f"<p><strong>Date:</strong> {summary['date']}</p>\n")
                f.write(f"<p><strong>Source:</strong> <a href='{summary['url']}'>{summary['url']}</a></p>\n")
                f.write(f"<p>{summary['summary']}</p>")

    return summaries

cookie = os.getenv('SUBSTACK_SID_COOKIE')
summaries = summarize_latest_articles(substack_urls, "md", "articles", cookie=cookie)

# Print summaries
for article in summaries:
    print(f"Article URL: {article['url']}")
    print(f"Title: {article['title']}")
    print(f"Date: {article['date']}")
    print(f"Summary: {article['summary']}")
    print("\n" + "="*50 + "\n")

# Close database connection
conn.close()
