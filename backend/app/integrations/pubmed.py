"""
Real NCBI E-utilities integration. No scraping, no mocked data.

Docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/
Rate limits: 3 req/s without an API key, 10 req/s with NCBI_API_KEY.
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@dataclass
class PubMedArticle:
    pmid: str
    title: str
    authors: list[str] = field(default_factory=list)
    journal: str | None = None
    publication_date: str | None = None
    abstract: str | None = None
    doi: str | None = None
    publication_types: list[str] = field(default_factory=list)


class PubMedIntegrationError(Exception):
    pass


class PubMedClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.ncbi_email:
            raise PubMedIntegrationError(
                "NCBI_EMAIL is required by NCBI's E-utilities usage policy. "
                "Set it in your environment before calling PubMed."
            )
        self._email = settings.ncbi_email
        self._api_key = settings.ncbi_api_key

    def _common_params(self) -> dict:
        params = {"tool": "clinical-evidence-intelligence", "email": self._email}
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    async def search(self, query: str, max_results: int = 20) -> list[str]:
        """Return a list of PMIDs matching the query."""
        params = {
            **self._common_params(),
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{EUTILS_BASE}/esearch.fcgi", params=params)
        if resp.status_code != 200:
            raise PubMedIntegrationError(f"PubMed esearch failed with status {resp.status_code}")
        data = resp.json()
        return data.get("esearchresult", {}).get("idlist", [])

    async def fetch_details(self, pmids: list[str]) -> list[PubMedArticle]:
        """Fetch and parse full metadata for a batch of PMIDs."""
        if not pmids:
            return []
        params = {
            **self._common_params(),
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{EUTILS_BASE}/efetch.fcgi", params=params)
        if resp.status_code != 200:
            raise PubMedIntegrationError(f"PubMed efetch failed with status {resp.status_code}")
        return self._parse_efetch_xml(resp.text)

    @staticmethod
    def _parse_efetch_xml(xml_text: str) -> list[PubMedArticle]:
        root = ET.fromstring(xml_text)
        articles: list[PubMedArticle] = []

        for article_el in root.findall(".//PubmedArticle"):
            medline = article_el.find("MedlineCitation")
            if medline is None:
                continue

            pmid_el = medline.find("PMID")
            pmid = pmid_el.text if pmid_el is not None else None
            if not pmid:
                continue

            article = medline.find("Article")
            title_el = article.find("ArticleTitle") if article is not None else None
            title = "".join(title_el.itertext()).strip() if title_el is not None else "Untitled"

            authors: list[str] = []
            for author_el in (article.findall(".//Author") if article is not None else []):
                last = author_el.findtext("LastName")
                fore = author_el.findtext("ForeName")
                if last:
                    authors.append(f"{fore} {last}".strip() if fore else last)

            journal_el = article.find("Journal/Title") if article is not None else None
            journal = journal_el.text if journal_el is not None else None

            pub_date_el = article.find("Journal/JournalIssue/PubDate") if article is not None else None
            publication_date = None
            if pub_date_el is not None:
                year = pub_date_el.findtext("Year")
                month = pub_date_el.findtext("Month")
                day = pub_date_el.findtext("Day")
                publication_date = " ".join(p for p in [year, month, day] if p) or None

            abstract_parts = []
            if article is not None:
                for ab_text_el in article.findall(".//AbstractText"):
                    text = "".join(ab_text_el.itertext()).strip()
                    label = ab_text_el.get("Label")
                    abstract_parts.append(f"{label}: {text}" if label else text)
            abstract = "\n".join(abstract_parts) if abstract_parts else None

            doi = None
            for id_el in article_el.findall(".//ArticleId"):
                if id_el.get("IdType") == "doi":
                    doi = id_el.text
                    break

            pub_types = [
                pt.text for pt in (article.findall(".//PublicationType") if article is not None else []) if pt.text
            ]

            articles.append(
                PubMedArticle(
                    pmid=pmid,
                    title=title,
                    authors=authors,
                    journal=journal,
                    publication_date=publication_date,
                    abstract=abstract,
                    doi=doi,
                    publication_types=pub_types,
                )
            )

        return articles

    async def search_and_fetch(self, query: str, max_results: int = 20) -> list[PubMedArticle]:
        pmids = await self.search(query, max_results=max_results)
        return await self.fetch_details(pmids)
