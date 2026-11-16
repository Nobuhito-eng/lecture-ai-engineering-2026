from app.retrieval import add_neighbor_pages


def page(document, number):
    return {"page_id": f"{document}-{number}", "document_id": document,
            "page": number, "title": f"p{number}", "content": f"本文{number}"}


def test_neighbors_keep_rank_deduplicate_and_stay_in_document():
    pages = [page("a", n) for n in (1, 2, 3, 4)] + [page("b", n) for n in (1, 2)]
    hits = [{**pages[1], "distance": 0.1}, {**pages[2], "distance": 0.2},
            {**pages[4], "distance": 0.3}]
    actual = add_neighbor_pages(hits, pages)
    assert [p["page_id"] for p in actual] == ["a-2", "a-3", "b-1", "a-1", "a-4", "b-2"]
    assert actual[0]["distance"] == 0.1
    assert (actual[3]["neighbor_of"], actual[3]["page_offset"], actual[3]["content"]) == ("a-2", -1, "本文1")


def test_missing_neighbor_and_empty_hits():
    only = page("a", 1)
    assert add_neighbor_pages([only], [only, page("b", 2)]) == [only]
    assert add_neighbor_pages([], [only]) == []
