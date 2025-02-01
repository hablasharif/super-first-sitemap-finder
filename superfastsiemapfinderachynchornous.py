import streamlit as st
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import pyperclip
import csv
import datetime
import concurrent.futures
from aiolimiter import AsyncLimiter
import cachetools
import ssl  # Import the ssl module

# Define a user agent to simulate a web browser
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"

# Disable SSL verification for a specific domain
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
ssl_context.hosts = ['0gomovies.si']  # Add your domain here

async def extract_all_urls_from_sitemap(session, sitemap_url):
    url_set = set()  # Use a set to store unique URLs

    async def extract_recursive(sitemap_url):
        try:
            async with session.get(sitemap_url, headers={"User-Agent": user_agent}, ssl=ssl_context) as response:
                if response.status == 200:
                    soup = BeautifulSoup(await response.text(), "xml")
                    url_elements = soup.find_all("loc")
                    urls = [url.text for url in url_elements]
                    url_set.update(urls)  # Add URLs to the set
                    sitemapindex_elements = soup.find_all("sitemap")

                    for sitemapindex_element in sitemapindex_elements:
                        sub_sitemap_url = sitemapindex_element.find("loc").text
                        await extract_recursive(sub_sitemap_url)

        except aiohttp.ClientError as e:
            pass

    await extract_recursive(sitemap_url)
    return list(url_set)  # Convert the set back to a list

def filter_urls(url_list):
    filtered_urls = []
    removed_urls = []

    filter_patterns = [
        "/casts/",
        "/cast/",
        "/directors/",
        "/director/",
        "/artist/",
        "/artists/",
        "/actors/",
        "/actor/",
        "/tag/",
        "/tags/",
        "/country/",
        "/genre/",
        "/stars/",
        "/release-year/",
        "/quality/",
        "/episode-date/",
        "/category/",
        "/lang/",
        "/year/",
        "/index/",
        "/network/",
        "/blog-tag/",
        "/blog-category/",
        "/archive/",
        "/sitemap-",
        "/author/",
        "/writer/",
        "/director_tv/",
        "/cast_tv/",
        "/movies-by-year/",
        "/uncategorized/",
        "/movies-by-genre/",
        "/tv-shows-by-network/",
        "/tv-shows-by-genre/",
        "/movies-by-file-size/",
        "/movies-by-quality/",
        "/comedy-show/",
        "/site-disclaimer/",
        "/about-us/",
        "/dmca/",
        "/report-broken-links/",
        "/contact-us/",
        ".xml",
        ".jpg",
        ".png",
        ".webp",
        ".jpeg",
    ]

    filter_extensions = [".jpg", ".png", ".webp", ".xml"]

    for url in url_list:
        if any(pattern in url for pattern in filter_patterns):
            removed_urls.append(url)
        else:
            parsed_url = urlparse(url)
            url_path = parsed_url.path
            file_extension = url_path.split(".")[-1].lower()
            if file_extension not in filter_extensions:
                filtered_urls.append(url)

    return filtered_urls, removed_urls

async def main():
    st.title("Sitemap URL Extractor")

    # Main domain input and extraction
    domain_input = st.text_area("Enter multiple domains (one per line):")
    domains = [domain.strip() for domain in domain_input.split("\n") if domain.strip()]

    all_url_set = set()  # Use a set to store all unique URLs

    if st.button("Extract URLs"):
        if domains:
            connector = aiohttp.TCPConnector(limit_per_host=100)  # Connection pooling
            async with aiohttp.ClientSession(connector=connector) as session:
                rate_limiter = AsyncLimiter(200)  # Increase the limit to 20 requests per second
                tasks = []
                for domain in domains:
                    if not domain.startswith("http://") and not domain.startswith("https://"):
                        domain = "https://" + domain

                    tasks.append(process_domain(session, domain, all_url_set, rate_limiter))

                await asyncio.gather(*tasks)

    if st.button("Copy All URLs"):
        if all_url_set:
            all_urls_text = "\n".join(all_url_set)
            pyperclip.copy(all_urls_text)
            st.success("All URLs copied to clipboard.")

    if domains:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %A %I-%M-%p")
        formatted_domains = " ".join(domain.replace("https://", "").replace("http://", "") for domain in domains)
        unfiltered_filename = f"Unfiltered URLs {formatted_domains} {timestamp}.csv"

        download_button_unfiltered = st.download_button(
            label="Download Unfiltered URLs as CSV",
            data="\n".join(all_url_set),
            key="download_button_unfiltered",
            file_name=unfiltered_filename,
        )

        filtered_urls, removed_urls = filter_urls(list(all_url_set))  # Convert set to list for filtering

        removed_filename = f"Removed URLs {formatted_domains} {timestamp}.csv"

        # Display the total number of removed URLs in the button label
        download_button_removed = st.download_button(
            label=f"Download Removed URLs as CSV ({len(removed_urls)} URLs)",
            data="\n".join(removed_urls),
            key="download_button_removed",
            file_name=removed_filename,
        )

        filtered_filename = f"Filtered URLs {formatted_domains} {len(filtered_urls)} {timestamp}.csv"

        download_button_filtered = st.download_button(
            label=f"Download Filtered URLs as CSV ({len(filtered_urls)} URLs)",
            data="\n".join(filtered_urls),
            key="download_button_filtered",
            file_name=filtered_filename,
        )

    # New section for user-defined sitemap extraction
    st.subheader("Extract URLs from a Specific Sitemap")
    user_sitemap_url = st.text_input("Enter a specific sitemap URL (e.g., https://image.bz-berlin.de/sitemap/news-sitemap.xml):")
    user_url_set = set()  # Use a set to store URLs from the user-defined sitemap

    if st.button("Extract URLs from Specific Sitemap"):
        if user_sitemap_url:
            connector = aiohttp.TCPConnector(limit_per_host=100)  # Connection pooling
            async with aiohttp.ClientSession(connector=connector) as session:
                rate_limiter = AsyncLimiter(200)  # Increase the limit to 20 requests per second
                url_list = await extract_all_urls_from_sitemap(session, user_sitemap_url)
                total_urls = len(url_list)

                if url_list:
                    st.success(f"Found {total_urls} URLs in the sitemap: {user_sitemap_url}")
                    st.text_area(f"URLs from {user_sitemap_url}", "\n".join(url_list))
                    user_url_set.update(url_list)  # Add URLs to the set
                else:
                    st.error(f"Failed to retrieve or extract URLs from {user_sitemap_url}.")

    if user_url_set:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %A %I-%M-%p")
        user_sitemap_filename = f"User Sitemap URLs {timestamp}.csv"

        download_button_user_sitemap = st.download_button(
            label="Download URLs from Specific Sitemap as CSV",
            data="\n".join(user_url_set),
            key="download_button_user_sitemap",
            file_name=user_sitemap_filename,
        )

if __name__ == "__main__":
    asyncio.run(main())
