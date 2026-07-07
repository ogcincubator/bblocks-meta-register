from pydantic import BaseModel, ConfigDict


class Maintainer(BaseModel):
    github: str | None = None
    email: str | None = None


class RegisterRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    register_url: str


class OrgSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    url: str | None


class OrgDetail(OrgSummary):
    maintainers: list[Maintainer]
    registers: list[RegisterRef]
