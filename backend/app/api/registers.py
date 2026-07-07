from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.repositories.deps import incoming_register_deps, outgoing_register_deps
from app.repositories.registers import get_register, list_registers
from app.schemas.register import RegisterDetail, RegisterDepEdge, RegisterSummary

router = APIRouter(prefix="/registers", tags=["registers"])


@router.get("", response_model=list[RegisterSummary])
async def list_registers_endpoint(session: SessionDep, org: str | None = None) -> list[RegisterSummary]:
    registers = await list_registers(session, org_id=org)
    return [RegisterSummary.model_validate(r) for r in registers]


@router.get("/{org_id}/{register_name}", response_model=RegisterDetail)
async def get_register_endpoint(org_id: str, register_name: str, session: SessionDep) -> RegisterDetail:
    register_id = f"{org_id}/{register_name}"
    register = await get_register(session, register_id)
    if register is None:
        raise HTTPException(status_code=404, detail=f"Register '{register_id}' not found")

    depends_on = [RegisterDepEdge(id=t, kind=k) for t, k in await outgoing_register_deps(session, register_id)]
    dependents = [RegisterDepEdge(id=s, kind=k) for s, k in await incoming_register_deps(session, register_id)]

    return RegisterDetail(
        **RegisterSummary.model_validate(register).model_dump(),
        modified=register.modified,
        last_crawled_at=register.last_crawled_at,
        last_crawl_status=register.last_crawl_status,
        last_error=register.last_error,
        bblocks=register.bblocks,
        depends_on=depends_on,
        dependents=dependents,
    )
