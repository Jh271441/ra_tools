from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import routes
from app.database import Base
from app.models import Scenario, ScenarioVersionResult, Version


def test_version_issue_pages_cover_tied_timestamps_without_duplicates(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        routes, "_configured_version_keys", lambda: ["release-a", "release-b"]
    )
    with Session(engine) as db:
        db.add_all([Version(version_key="release-a"), Version(version_key="release-b")])
        for sid in ["103", "101", "105", "102", "104"]:
            db.add(Scenario(scenario_id=sid))
            for version in ["release-b", "release-a"]:
                db.add(
                    ScenarioVersionResult(
                        version_key=version,
                        scenario_id=sid,
                        precision_label="FN",
                        updated_at=datetime(2026, 9, 30),
                    )
                )
        db.commit()
        pages = [
            routes.issues(
                db, version="release-a", precision_label="FN", page=page, page_size=2
            )
            for page in (1, 2, 3)
        ]
        ids = [row.scenario_id for page in pages for row in page.items]
        assert all(page.total == 5 for page in pages)
        assert len(ids) == len(set(ids)) == 5
        assert set(ids) == {"101", "102", "103", "104", "105"}
        assert all(
            row.version_key == "release-a" for page in pages for row in page.items
        )
        # A different page size and revisiting the first page preserve row identities.
        whole = routes.issues(
            db, version="release-a", precision_label="FN", page=1, page_size=10
        )
        assert ids == [row.scenario_id for row in whole.items]
        assert ids[:2] == [
            row.scenario_id
            for row in routes.issues(
                db, version="release-a", precision_label="FN", page=1, page_size=2
            ).items
        ]
