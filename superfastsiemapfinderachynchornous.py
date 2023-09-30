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

# Define a user agent to simulate a web browser
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"

async def extract_sitemap_url(session, domain):
    sitemap_urls = [
        urljoin(domain, "sitemap_index.xml"),
        urljoin(domain, "sitemap.xml"),
        urljoin(domain, "sitemap_gn.xml")
    ]

    for sitemap_url in sitemap_urls:
        try:
            async with session.get(sitemap_url, headers={"User-Agent": user_agent}) as response:
                if response.status == 200:
                    return sitemap_url
        except aiohttp.ClientError as e:
            pass

    return None

async def extract_all_urls_from_sitemap(session, sitemap_url):
    url_list = []

    async def extract_recursive(sitemap_url):
        try:
            async with session.get(sitemap_url, headers={"User-Agent": user_agent}) as response:
                if response.status == 200:
                    soup = BeautifulSoup(await response.text(), "xml")
                    url_elements = soup.find_all("loc")
                    urls = [url.text for url in url_elements]
                    url_list.extend(urls)
                    sitemapindex_elements = soup.find_all("sitemap")

                    for sitemapindex_element in sitemapindex_elements:
                        sub_sitemap_url = sitemapindex_element.find("loc").text
                        await extract_recursive(sub_sitemap_url)

        except aiohttp.ClientError as e:
            pass

    await extract_recursive(sitemap_url)
    return url_list

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
        ".webp"
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

async def process_domain(session, domain, all_url_list, limiter):
    async with limiter:
        sitemap_urls = [
            urljoin(domain, "sitemap_index.xml"),
            urljoin(domain, "sitemap.xml"),
            urljoin(domain, "sitemap_gn.xml")
        ]
        
        for sitemap_url in sitemap_urls:
            try:
                st.text(f"Trying sitemap URL: {sitemap_url}")
                async with session.get(sitemap_url, headers={"User-Agent": user_agent}) as response:
                    if response.status == 200:
                        url_list = await extract_all_urls_from_sitemap(session, sitemap_url)
                        total_urls = len(url_list)

                        if url_list:
                            st.success(f"Found {total_urls} URLs in the sitemap of {domain}:")
                            st.text_area(f"URLs from {domain}", "\n".join(url_list))
                            all_url_list.extend(url_list)
                            return  # Exit the loop if successful
            except aiohttp.ClientError as e:
                pass

        st.error(f"Failed to retrieve or extract URLs from {domain}.")

async def main():
    st.title("Sitemap URL Extractor")

    domain_input = st.text_area("Enter multiple domains (one per line):")
    domains = [domain.strip() for domain in domain_input.split("\n") if domain.strip()]

    all_url_list = []

    if st.button("Extract URLs"):
        if domains:
            connector = aiohttp.TCPConnector(limit_per_host=10)  # Connection pooling
            async with aiohttp.ClientSession(connector=connector) as session:
                rate_limiter = AsyncLimiter(10)  # Rate limiting (adjust the limit)
                tasks = []
                for domain in domains:
                    if not domain.startswith("http://") and not domain.startswith("https://"):
                        domain = "https://" + domain

                    tasks.append(process_domain(session, domain, all_url_list, rate_limiter))

                await asyncio.gather(*tasks)

    if st.button("Copy All URLs"):
        if all_url_list:
            all_urls_text = "\n".join(all_url_list)
            pyperclip.copy(all_urls_text)
            st.success("All URLs copied to clipboard.")

    if domains:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %A %I-%M-%p")
        formatted_domains = " ".join(domain.replace("https://", "").replace("http://", "") for domain in domains)
        unfiltered_filename = f"Unfiltered URLs {formatted_domains} {timestamp}.csv"

        download_button_unfiltered = st.download_button(
            label="Download Unfiltered URLs as CSV",
            data="\n".join(all_url_list),
            key="download_button_unfiltered",
            file_name=unfiltered_filename,
        )

        filtered_urls, removed_urls = filter_urls(all_url_list)

        removed_filename = f"Removed URLs {formatted_domains} {timestamp}.csv"

        download_button_removed = st.download_button(
            label="Download Removed URLs as CSV",
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

    # Count the number of input URLs
    num_input_urls = len(all_url_list)

    # Count the number of removed URLs
    num_removed_urls = len(removed_urls)

    # Display the count of input URLs, removed URLs, and unfiltered URLs
    st.write(f"Number of Input URLs: {num_input_urls}")
    st.write(f"Number of Removed URLs: {num_removed_urls}")
    st.write(f"Number of Unfiltered URLs: {num_input_urls - num_removed_urls}")

if __name__ == "__main__":
    asyncio.run(main())

# Create a link to the external URL
url = "https://website-titles-and-h1-tag-checke.streamlit.app/"
link_text = "VISIT THIS IF YOU WANT TO PULL WEBSITE ALL TITLES AND H1 TAG TITLE THEN VISIT THIS"

# Display the link
st.markdown(f"[{link_text}]({url})")
