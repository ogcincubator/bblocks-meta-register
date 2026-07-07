from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.repositories.orgs import get_org, list_orgs
from app.schemas.org import OrgDetail, OrgSummary

router = APIRouter(prefix="/orgs", tags=["orgs"])


@router.get("", response_model=list[OrgSummary])
async def list_orgs_endpoint(session: SessionDep) -> list[OrgSummary]:
    orgs = await list_orgs(session)
    return [OrgSummary.model_validate(org) for org in orgs]


@router.get("/{org_id}", response_model=OrgDetail)
async def get_org_endpoint(org_id: str, session: SessionDep) -> OrgDetail:
    org = await get_org(session, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail=f"Org '{org_id}' not found")
    return OrgDetail.model_validate(org)
