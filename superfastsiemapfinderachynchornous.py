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

async def extract_sitemap_urls(session, domain):
    # Try predefined sitemap URLs first
    predefined_sitemap_urls = [
        urljoin(domain, "sitemap_index.xml"),
        urljoin(domain, "sitemap.xml"),
        urljoin(domain, "sitemap_gn.xml"),
        urljoin(domain, "news.xml")
    ]

    sitemap_urls = []

    # Check predefined sitemap URLs
    for sitemap_url in predefined_sitemap_urls:
        try:
            async with session.get(sitemap_url, headers={"User-Agent": user_agent}, ssl=ssl_context) as response:
                if response.status == 200:
                    sitemap_urls.append(sitemap_url)
        except aiohttp.ClientError as e:
            pass

    # If no sitemap found in predefined URLs, check robots.txt for .xml URLs
    if not sitemap_urls:
        robots_url = urljoin(domain, "robots.txt")
        try:
            async with session.get(robots_url, headers={"User-Agent": user_agent}, ssl=ssl_context) as response:
                if response.status == 200:
                    robots_content = await response.text()
                    for line in robots_content.splitlines():
                        # Look for lines starting with "Sitemap:" and ending with .xml
                        if line.strip().lower().startswith("sitemap:") and line.strip().lower().endswith(".xml"):
                            sitemap_url = line.split(":", 1)[1].strip()
                            # If the sitemap URL is absolute, use it directly
                            if sitemap_url.startswith("http"):
                                sitemap_urls.append(sitemap_url)
                            else:
                                sitemap_urls.append(urljoin(domain, sitemap_url))
        except aiohttp.ClientError as e:
            pass

    return sitemap_urls

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

async def process_domain(session, domain, all_url_set, limiter):
    try:
        async with limiter:
            sitemap_urls = await extract_sitemap_urls(session, domain)
            if sitemap_urls:
                st.text(f"Found sitemap URLs: {', '.join(sitemap_urls)}")
                for sitemap_url in sitemap_urls:
                    url_list = await extract_all_urls_from_sitemap(session, sitemap_url)
                    total_urls = len(url_list)

                    if url_list:
                        st.success(f"Found {total_urls} URLs in the sitemap: {sitemap_url}")
                        st.text_area(f"URLs from {sitemap_url}", "\n".join(url_list))
                        all_url_set.update(url_list)  # Add URLs to the global set
            else:
                st.error(f"Failed to retrieve or extract sitemap URLs from {domain}.")
    except asyncio.TimeoutError:
        st.error(f"Timeout while processing {domain}.")
    except Exception as e:
        st.error(f"Error processing {domain}: {str(e)}")

# New function to extract URLs from robots.txt for multiple domains
async def extract_robots_txt_urls(session, domain):
    robots_url = urljoin(domain, "robots.txt")
    urls = []

    try:
        async with session.get(robots_url, headers={"User-Agent": user_agent}, ssl=ssl_context) as response:
            if response.status == 200:
                try:
                    robots_content = await response.text()
                    for line in robots_content.splitlines():
                        # Look for lines starting with "Sitemap:", "Allow:", or "Disallow:"
                        if line.strip().lower().startswith(("sitemap:", "allow:", "disallow:")):
                            url = line.split(":", 1)[1].strip()
                            if url.startswith("http"):
                                urls.append(url)
                            else:
                                urls.append(urljoin(domain, url))
                except UnicodeDecodeError:
                    st.error(f"Failed to decode robots.txt content from {robots_url}. It may contain binary data.")
                except Exception as e:
                    st.error(f"Error processing robots.txt content from {robots_url}: {str(e)}")
            else:
                st.error(f"Failed to fetch robots.txt from {robots_url}. Status code: {response.status}")
    except aiohttp.ClientError as e:
        st.error(f"Error fetching robots.txt from {domain}: {str(e)}")

    return urls

async def process_robots_txt_domains(session, domains, robots_url_set, limiter):
    tasks = []
    for domain in domains:
        if not domain.startswith("http://") and not domain.startswith("https://"):
            domain = "https://" + domain
        tasks.append(extract_robots_txt_urls(session, domain))

    results = await asyncio.gather(*tasks)
    for urls in results:
        robots_url_set.update(urls)

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
    user_sitemap_url = st.text_input("Enter a specific sitemap URL (e.g., https://example.com/sitemap.xml):")
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

    # New section for extracting URLs from robots.txt for multiple domains
    st.subheader("Extract URLs from robots.txt")
    robots_domain_input = st.text_area("Enter multiple domains (one per line) to extract URLs from their robots.txt:")
    robots_domains = [domain.strip() for domain in robots_domain_input.split("\n") if domain.strip()]
    robots_url_set = set()  # Use a set to store URLs from robots.txt

    if st.button("Extract URLs from robots.txt"):
        if robots_domains:
            connector = aiohttp.TCPConnector(limit_per_host=100)  # Connection pooling
            async with aiohttp.ClientSession(connector=connector) as session:
                rate_limiter = AsyncLimiter(200)  # Increase the limit to 20 requests per second
                await process_robots_txt_domains(session, robots_domains, robots_url_set, rate_limiter)

                if robots_url_set:
                    st.success(f"Found {len(robots_url_set)} URLs in robots.txt for the provided domains.")
                    st.text_area(f"URLs from robots.txt", "\n".join(robots_url_set))
                else:
                    st.error("No URLs found in robots.txt for the provided domains.")

    if robots_url_set:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %A %I-%M-%p")
        robots_filename = f"Robots URLs {timestamp}.csv"

        download_button_robots = st.download_button(
            label="Download URLs from robots.txt as CSV",
            data="\n".join(robots_url_set),
            key="download_button_robots",
            file_name=robots_filename,
        )

if __name__ == "__main__":
    asyncio.run(main())
