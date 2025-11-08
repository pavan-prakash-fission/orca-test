from sqlmodel import Field, SQLModel
from typing import Optional


class DatabaseReleaseTagDistributionListLink(SQLModel, table=True):
    __tablename__ = "database_release_tag_distribution_list_link"

    database_release_tag_id: Optional[int] = Field(
        default=None,
        foreign_key="database_release_tag.id",
        primary_key=True
    )
    distribution_list_id: Optional[int] = Field(
        default=None,
        foreign_key="distribution_lists.id",
        primary_key=True
    )


class OutputDetailDatabaseReleaseTagLink(SQLModel, table=True):
    __tablename__ = "output_detail_database_release_tag_link"

    output_detail_id: Optional[int] = Field(
        default=None,
        foreign_key="output_details.id",
        primary_key=True
    )
    database_release_tag_id: Optional[int] = Field(
        default=None,
        foreign_key="database_release_tag.id",
        primary_key=True
    )