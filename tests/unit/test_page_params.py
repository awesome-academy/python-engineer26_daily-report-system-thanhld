import pytest
from pydantic import ValidationError

from app.core.constants import MAX_PAGE, MAX_PAGE_SIZE
from app.core.pagination import Page, PageParams


def test_defaults_to_first_page_of_twenty() -> None:
    params = PageParams()

    assert (params.page, params.page_size, params.offset) == (1, 20, 0)


def test_offset_skips_previous_pages() -> None:
    assert PageParams(page=3, page_size=10).offset == 20


@pytest.mark.parametrize(
    "values",
    [{"page": 0}, {"page": MAX_PAGE + 1}, {"page_size": 0}, {"page_size": MAX_PAGE_SIZE + 1}],
)
def test_rejects_out_of_range_values(values: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        PageParams.model_validate(values)


def test_page_build_returns_data_and_meta() -> None:
    page = Page[int].build([1, 2], total=12, params=PageParams(page=2, page_size=2))

    assert page.model_dump() == {"data": [1, 2], "meta": {"page": 2, "page_size": 2, "total": 12}}
