"""Team management endpoints.

Lists the club's teams and lets authorized staff create new teams.

All protected operations reuse authentication and role checks from app.core.
"""

from fastapi import APIRouter
from ..core import *  # Shared database, schemas, authorization and business helpers.

router = APIRouter()

# Purpose: list teams handles the teams feature flow and returns its API result.
@router.get("/api/teams")
async def list_teams(user: dict = Depends(get_current_user)):
    docs=await db.teams.find().sort("name",1).to_list(200)
    return [{"id":str(x["_id"]),"name":x["name"],"description":x.get("description","")} for x in docs]

# Purpose: create team handles the teams feature flow and returns its API result.
@router.post("/api/teams",status_code=201)
async def create_team(data: TeamCreate, request: Request, actor: dict = Depends(allow("Founder","Core Management"))):
    try: res=await db.teams.insert_one({"name":data.name.strip(),"description":data.description,"created_at":utcnow()})
    except DuplicateKeyError: raise HTTPException(409,"Team already exists")
    await audit(actor,"team_created",str(res.inserted_id),{"name":data.name},request)
    return {"id":str(res.inserted_id),"name":data.name,"description":data.description}

