from app.integrations.pubmed import PubMedClient

SAMPLE_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>Metformin and cardiovascular outcomes in type 2 diabetes</ArticleTitle>
        <Journal><Title>Diabetes Care</Title>
          <JournalIssue><PubDate><Year>2022</Year><Month>Jun</Month></PubDate></JournalIssue>
        </Journal>
        <AbstractText Label="BACKGROUND">Metformin is widely used.</AbstractText>
        <AbstractText Label="RESULTS">Reduced cardiovascular events were observed.</AbstractText>
        <AuthorList>
          <Author><LastName>Smith</LastName><ForeName>Jane</ForeName></Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
      </Article>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/example.doi</ArticleId>
      </ArticleIdList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_parses_core_fields_from_efetch_xml():
    articles = PubMedClient._parse_efetch_xml(SAMPLE_EFETCH_XML)
    assert len(articles) == 1
    article = articles[0]
    assert article.pmid == "12345678"
    assert "Metformin" in article.title
    assert article.journal == "Diabetes Care"
    assert article.publication_date == "2022 Jun"
    assert article.authors == ["Jane Smith"]
    assert "BACKGROUND" in article.abstract and "RESULTS" in article.abstract
    assert article.doi == "10.1000/example.doi"
    assert "Randomized Controlled Trial" in article.publication_types


def test_missing_pmid_articles_are_skipped():
    xml = "<PubmedArticleSet><PubmedArticle><MedlineCitation></MedlineCitation></PubmedArticle></PubmedArticleSet>"
    assert PubMedClient._parse_efetch_xml(xml) == []
