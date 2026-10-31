"""Club Hub feature endpoints.

Projects, coding challenges, events, library resources, polls, discussions,
rewards, attendance, mentoring, member messages and certificates.

All protected operations reuse authentication and role checks from app.core.
"""

from fastapi import APIRouter
from ..core import *  # Shared database, schemas, authorization and business helpers.

router = APIRouter()

# Hub collections and role names were originally declared beside the Hub endpoints.
# Keep them in this router so collection lookups and staff-only views share one source.
HUB_COLLECTIONS = {
    "projects": db.hub_projects,
    "challenges": db.hub_challenges,
    "events": db.hub_events,
    "resources": db.hub_resources,
    "discussions": db.hub_discussions,
    "rewards": db.hub_rewards,
    "attendance": db.hub_attendance,
    "polls": db.hub_polls,
    "mentorship": db.hub_mentorship,
    "messages": db.hub_messages,
    "certificates": db.hub_certificates,
}

# Faculty can manage Hub content and review challenges alongside club management.
HUB_STAFF = {"Founder", "Core Management", "Faculty"}

# Purpose: hub clean handles the hub feature flow and returns its API result.
def hub_clean(doc):
    return {k: (str(v) if k == "_id" else v) for k,v in {
        "_id":doc["_id"],"type":doc.get("type",""),"title":doc.get("title",""),
        "description":doc.get("description",""),"status":doc.get("status","Open"),
        "category":doc.get("category",""),"url":doc.get("url",""),
        "team":doc.get("team",""),"created_by":doc.get("created_by_name",""),
        "created_at":doc.get("created_at"),"due_date":doc.get("due_date"),
        "points":doc.get("points",0),"members":doc.get("members",[]),
        "comments":doc.get("comments",[]),"submissions":doc.get("submissions",[]),"rsvps":doc.get("rsvps",[]),"options":doc.get("options",[]),"votes":[{"option":v.get("option")} for v in doc.get("votes",[])],
    }.items()}

# Purpose: hub profile handles the hub feature flow and returns its API result.
@router.get("/api/hub/profile")
async def hub_profile(user: dict = Depends(get_current_user)):
    uid=user["_id"]
    progress=await member_progress_summary(uid)
    done=progress["completed_tasks"]
    review=progress["pending_reviews"]
    credits=progress["credits"]
    achievements=[]
    for threshold,title,desc,icon in [(1,"First Mission","Complete your first task","🎯"),(10,"Task Machine","Complete 10 tasks","⚡"),(25,"Consistent Builder","Complete 25 tasks","🛠️")]:
        if done>=threshold: achievements.append({"title":title,"description":desc,"icon":icon})
    if credits>=100: achievements.append({"title":"Credit Century","description":"Earn 100 credits","icon":"🏅"})
    return {**progress,"achievements":achievements}

# Purpose: hub list handles the hub feature flow and returns its API result.
@router.get("/api/hub/{collection}")
async def hub_list(collection: str, user: dict = Depends(get_current_user)):
    target=HUB_COLLECTIONS.get(collection)
    if target is None: raise HTTPException(404,"Hub section not found")
    if collection=="messages":
        uid=str(user["_id"])
        docs=await db.hub_messages.find({"$or":[{"sender_id":uid},{"recipient_id":uid}]}).sort("created_at",-1).to_list(200)
        return [{"id":str(x["_id"]),"sender":x["sender_name"],"recipient":x["recipient_name"],"sender_id":x["sender_id"],"recipient_id":x["recipient_id"],"message":x["message"],"created_at":x["created_at"]} for x in docs]
    if collection=="certificates":
        docs=await db.hub_certificates.find({"user_id":str(user["_id"])}).to_list(50)
        return [{"id":str(x["_id"]),"name":x["name"],"code":x["code"],"completed_tasks":x["completed_tasks"],"issued_at":x["issued_at"]} for x in docs]
    if collection=="attendance":
        docs=await db.hub_attendance.find({"status":"Open"}).sort("created_at",-1).to_list(100)
        return [{"id":str(x["_id"]),"title":x["title"],"description":"","status":x["status"],"category":"Attendance","url":"","created_by":"","created_at":x.get("created_at"),"due_date":"","points":0,"members":[],"comments":[],"code":x["code"] if user.get("role") in HUB_STAFF else None,"attendee_count":len(x.get("attendees",[])),"checked_in":str(user["_id"]) in x.get("attendees",[])} for x in docs]
    query={"status":{"$ne":"Archived"}}
    if collection=="projects" and user.get("role")=="Member":
        query={"$and":[{"status":{"$ne":"Archived"}},{"$or":[{"visibility":"Club"},{"members":str(user["_id"])}]}]}
    docs=await target.find(query).sort("created_at",-1).to_list(200)
    cleaned=[]
    for doc in docs:
        item=hub_clean(doc)
        if collection=="challenges" and user.get("role") not in HUB_STAFF:
            item["submissions"]=[sub for sub in item.get("submissions",[]) if sub.get("user_id")==str(user["_id"])]
        cleaned.append(item)
    return cleaned

# Purpose: hub create handles the hub feature flow and returns its API result.
@router.post("/api/hub/{collection}",status_code=201)
async def hub_create(collection: str, request: Request, user: dict = Depends(get_current_user)):
    target=HUB_COLLECTIONS.get(collection)
    if target is None: raise HTTPException(404,"Hub section not found")
    if user.get("role") not in HUB_STAFF and collection not in {"discussions","messages","mentorship"}:
        raise HTTPException(403,"Only club management can publish this item")
    data=await request.json()
    if collection=="mentorship":
        mentor=str(data.get("mentor","")).strip()[:120]
        goal=str(data.get("goal","")).strip()[:1000]
        if not mentor or not goal: raise HTTPException(422,"Mentor name and learning goal are required")
        doc={"user_id":str(user["_id"]),"member_name":user.get("name","Member"),"mentor":mentor,"goal":goal,"status":"Pending","created_at":utcnow()}
        result=await db.hub_mentorship.insert_one(doc)
        await audit(user,"hub_mentorship_requested",str(result.inserted_id),{"mentor":mentor},request)
        return {"ok":True}
    if collection=="messages":
        recipient_id=str(data.get("recipient_id","")).strip()
        message=str(data.get("message","")).strip()
        if not recipient_id or not message or len(message)>2000: raise HTTPException(422,"Choose a member and write a message up to 2000 characters")
        recipient=await db.users.find_one({"_id":oid(recipient_id),"status":"Active"})
        if not recipient: raise HTTPException(404,"Active recipient not found")
        doc={"sender_id":str(user["_id"]),"sender_name":user.get("name","Member"),"recipient_id":str(recipient["_id"]),"recipient_name":recipient.get("name","Member"),"message":message,"created_at":utcnow()}
        await db.hub_messages.insert_one(doc)
        await create_notification(recipient,"New TechNova message",f'{user.get("name","A member")} sent you a message.')
        return {"ok":True}
    if collection=="attendance":
        title=str(data.get("title","")).strip()[:120]
        if len(title)<3: raise HTTPException(422,"Session title is required")
        code=token_urlsafe(7)
        doc={"title":title,"code":code,"status":"Open","created_by":user["_id"],"created_at":utcnow(),"attendees":[]}
        result=await db.hub_attendance.insert_one(doc)
        await audit(user,"hub_attendance_opened",str(result.inserted_id),{"title":title},request)
        return {"id":str(result.inserted_id),"title":title,"code":code,"status":"Open"}
    title=str(data.get("title","")).strip()[:120]
    if len(title)<3: raise HTTPException(422,"Title must contain at least 3 characters")
    url=str(data.get("url","")).strip()[:500]
    if url and not re.match(r"^https?://",url,re.I): raise HTTPException(422,"Use a valid http or https link")
    if collection=="polls":
        options=[str(x).strip()[:100] for x in data.get("options",[]) if str(x).strip()][:8]
        if len(options)<2 or len(set(options))<2: raise HTTPException(422,"A poll needs at least two different options")
    doc={"type":collection,"title":title,"description":str(data.get("description","")).strip()[:4000],
         "status":"Open","category":str(data.get("category","")).strip()[:60],"url":url,
         "team":str(data.get("team","")).strip()[:80],"visibility":"Club","created_by":user["_id"],
         "created_by_name":user.get("name","Member"),"created_at":utcnow(),"due_date":str(data.get("due_date",""))[:40],
         "points":max(0,min(int(data.get("points",0) or 0),1000)),"options":[str(x).strip()[:100] for x in data.get("options",[]) if str(x).strip()][:8],"votes":[],"members":[str(user["_id"])],"comments":[],"submissions":[]}
    res=await target.insert_one(doc)
    await audit(user,f"hub_{collection}_created",str(res.inserted_id),{"title":title},request)
    return hub_clean({"_id":res.inserted_id,**doc})

# Purpose: hub join project handles the hub feature flow and returns its API result.
@router.post("/api/hub/projects/{item_id}/join")
async def hub_join_project(item_id: str, request: Request, user: dict = Depends(get_current_user)):
    project=await db.hub_projects.find_one({"_id":oid(item_id),"status":{"$ne":"Archived"}})
    if not project: raise HTTPException(404,"Project not found")
    await db.hub_projects.update_one({"_id":project["_id"]},{"$addToSet":{"members":str(user["_id"])}})
    await audit(user,"hub_project_joined",item_id,{"title":project.get("title")},request)
    return {"ok":True}

# Purpose: hub submit challenge handles the hub feature flow and returns its API result.
@router.post("/api/hub/challenges/{item_id}/submit")
async def hub_submit_challenge(item_id: str, request: Request, user: dict = Depends(get_current_user)):
    challenge=await db.hub_challenges.find_one({"_id":oid(item_id),"status":{"$ne":"Archived"}})
    if not challenge: raise HTTPException(404,"Challenge not found")
    data=await request.json(); code=str(data.get("code",""))
    if not code.strip() or len(code)>50000: raise HTTPException(422,"Code is required and limited to 50 KB")
    entry={"user_id":str(user["_id"]),"member_name":user.get("name","Member"),"language":str(data.get("language",""))[:40],"code":code,"submitted_at":utcnow(),"review_status":"Submitted"}
    await db.hub_challenges.update_one({"_id":challenge["_id"]},{"$push":{"submissions":entry}})
    await audit(user,"hub_challenge_submitted",item_id,{"language":entry["language"]},request)
    return {"ok":True,"message":"Code saved for review. Secure code execution is not configured."}

# Purpose: hub discussion comment handles the hub feature flow and returns its API result.
@router.post("/api/hub/discussions/{item_id}/comment")
async def hub_discussion_comment(item_id: str, request: Request, user: dict = Depends(get_current_user)):
    doc=await db.hub_discussions.find_one({"_id":oid(item_id)})
    if not doc: raise HTTPException(404,"Discussion not found")
    data=await request.json(); message=str(data.get("message","")).strip()
    if not message or len(message)>2000: raise HTTPException(422,"Comment must be 1–2000 characters")
    comment={"user_id":str(user["_id"]),"name":user.get("name","Member"),"role":user.get("role","Member"),"message":message,"created_at":utcnow()}
    await db.hub_discussions.update_one({"_id":doc["_id"]},{"$push":{"comments":comment}})
    return {"ok":True}

# Purpose: hub archive handles the hub feature flow and returns its API result.
@router.post("/api/hub/{collection}/{item_id}/archive")
async def hub_archive(collection: str,item_id: str,request: Request,user: dict=Depends(allow("Founder","Core Management"))):
    target=HUB_COLLECTIONS.get(collection)
    if target is None: raise HTTPException(404,"Hub section not found")
    result=await target.update_one({"_id":oid(item_id)},{"$set":{"status":"Archived","archived_at":utcnow(),"archived_by":user["_id"]}})
    if not result.matched_count: raise HTTPException(404,"Record not found")
    await audit(user,f"hub_{collection}_archived",item_id,{},request)
    return {"ok":True}


# Attendance, event registration, reward requests and challenge review
# Purpose: hub attendance list handles the hub feature flow and returns its API result.
@router.get("/api/hub/attendance")
async def hub_attendance_list(user: dict = Depends(get_current_user)):
    docs=await db.hub_attendance.find({"status":"Open"}).sort("created_at",-1).to_list(100)
    return [{"id":str(x["_id"]),"title":x["title"],"code":x["code"] if user.get("role") in HUB_STAFF else None,"created_at":x.get("created_at"),"attendee_count":len(x.get("attendees",[])),"checked_in":str(user["_id"]) in x.get("attendees",[])} for x in docs]

# Purpose: hub attendance create handles the hub feature flow and returns its API result.
@router.post("/api/hub/attendance")
async def hub_attendance_create(request: Request,user: dict=Depends(allow("Founder","Core Management","Faculty"))):
    data=await request.json()
    title=str(data.get("title","")).strip()[:120]
    if len(title)<3: raise HTTPException(422,"Session title is required")
    code=token_urlsafe(7)
    doc={"title":title,"code":code,"status":"Open","created_by":user["_id"],"created_at":utcnow(),"attendees":[]}
    result=await db.hub_attendance.insert_one(doc)
    await audit(user,"hub_attendance_opened",str(result.inserted_id),{"title":title},request)
    return {"id":str(result.inserted_id),"title":title,"code":code,"status":"Open"}

# Purpose: hub attendance checkin handles the hub feature flow and returns its API result.
@router.post("/api/hub/attendance/check-in")
async def hub_attendance_checkin(request: Request,user: dict=Depends(get_current_user)):
    data=await request.json(); code=str(data.get("code","")).strip()
    session=await db.hub_attendance.find_one({"code":code,"status":"Open"})
    if not session: raise HTTPException(404,"Invalid or closed attendance code")
    result=await db.hub_attendance.update_one({"_id":session["_id"],"attendees":{"$ne":str(user["_id"])}},{"$addToSet":{"attendees":str(user["_id"])}})
    if not result.modified_count: raise HTTPException(409,"You have already checked in")
    await audit(user,"hub_attendance_checkin",str(session["_id"]),{"title":session["title"]},request)
    return {"ok":True,"message":"Attendance recorded"}

# Purpose: hub event rsvp handles the hub feature flow and returns its API result.
@router.post("/api/hub/events/{item_id}/rsvp")
async def hub_event_rsvp(item_id: str,request: Request,user: dict=Depends(get_current_user)):
    event=await db.hub_events.find_one({"_id":oid(item_id),"status":{"$ne":"Archived"}})
    if not event: raise HTTPException(404,"Event not found")
    await db.hub_events.update_one({"_id":event["_id"]},{"$addToSet":{"rsvps":str(user["_id"])}})
    return {"ok":True,"message":"Your event registration is saved"}

# Purpose: hub reward requests handles the hub feature flow and returns its API result.
@router.get("/api/hub/rewards/requests")
async def hub_reward_requests(user: dict=Depends(get_current_user)):
    query={} if user.get("role") in HUB_STAFF else {"user_id":str(user["_id"])}
    docs=await db.hub_reward_requests.find(query).sort("created_at",-1).to_list(200)
    return [{"id":str(x["_id"]),"reward_title":x["reward_title"],"member_name":x.get("member_name"),"status":x.get("status"),"created_at":x.get("created_at"),"note":x.get("note","")} for x in docs]

# Purpose: hub reward request handles the hub feature flow and returns its API result.
@router.post("/api/hub/rewards/{item_id}/request")
async def hub_reward_request(item_id: str,request: Request,user: dict=Depends(get_current_user)):
    reward=await db.hub_rewards.find_one({"_id":oid(item_id),"status":{"$ne":"Archived"}})
    if not reward: raise HTTPException(404,"Reward not found")
    existing=await db.hub_reward_requests.find_one({"reward_id":reward["_id"],"user_id":str(user["_id"]),"status":"Pending"})
    if existing: raise HTTPException(409,"You already have a pending request for this reward")
    doc={"reward_id":reward["_id"],"reward_title":reward["title"],"user_id":str(user["_id"]),"member_name":user.get("name","Member"),"status":"Pending","note":"","created_at":utcnow()}
    await db.hub_reward_requests.insert_one(doc)
    await audit(user,"hub_reward_requested",item_id,{"title":reward["title"]},request)
    return {"ok":True,"message":"Reward request sent to club management"}

# Purpose: hub reward decision handles the hub feature flow and returns its API result.
@router.post("/api/hub/rewards/requests/{request_id}/decision")
async def hub_reward_decision(request_id: str,request: Request,user: dict=Depends(allow("Founder","Core Management"))):
    data=await request.json(); decision=str(data.get("decision",""))
    if decision not in {"Approved","Declined"}: raise HTTPException(422,"Choose Approved or Declined")
    note=str(data.get("note","")).strip()[:500]
    result=await db.hub_reward_requests.update_one({"_id":oid(request_id),"status":"Pending"},{"$set":{"status":decision,"note":note,"reviewed_by":user["_id"],"reviewed_at":utcnow()}})
    if not result.modified_count: raise HTTPException(409,"Request is no longer pending")
    await audit(user,"hub_reward_"+decision.lower(),request_id,{"note":note},request)
    return {"ok":True}

# Purpose: hub challenge review handles the hub feature flow and returns its API result.
@router.post("/api/hub/challenges/{item_id}/review")
async def hub_challenge_review(item_id: str,request: Request,user: dict=Depends(allow("Founder","Core Management","Faculty"))):
    data=await request.json()
    member_id=str(data.get("user_id","")).strip()
    decision=str(data.get("decision",""))
    feedback=str(data.get("feedback","")).strip()[:1000]
    if decision not in {"Accepted","Needs changes"}: raise HTTPException(422,"Invalid review decision")
    challenge=await db.hub_challenges.find_one({"_id":oid(item_id)})
    if not challenge: raise HTTPException(404,"Challenge not found")
    result=await db.hub_challenges.update_one({"_id":challenge["_id"],"submissions.user_id":member_id},{"$set":{"submissions.$.review_status":decision,"submissions.$.review_feedback":feedback,"submissions.$.reviewed_at":utcnow(),"submissions.$.reviewed_by":user.get("name","Staff")}})
    if not result.modified_count: raise HTTPException(404,"Submission not found")
    await audit(user,"hub_challenge_reviewed",item_id,{"user_id":member_id,"decision":decision},request)
    return {"ok":True}


# Polls and mentorship requests
# Purpose: hub poll vote handles the hub feature flow and returns its API result.
@router.post("/api/hub/polls/{item_id}/vote")
async def hub_poll_vote(item_id: str,request: Request,user: dict=Depends(get_current_user)):
    poll=await db.hub_polls.find_one({"_id":oid(item_id),"status":{"$ne":"Archived"}})
    if not poll: raise HTTPException(404,"Poll not found")
    data=await request.json(); option=str(data.get("option","")).strip()
    if option not in poll.get("options",[]): raise HTTPException(422,"Choose a valid poll option")
    previous=await db.hub_polls.find_one({"_id":poll["_id"],"votes.user_id":str(user["_id"])})
    if previous: raise HTTPException(409,"You have already voted")
    await db.hub_polls.update_one({"_id":poll["_id"]},{"$push":{"votes":{"user_id":str(user["_id"]),"option":option,"voted_at":utcnow()}}})
    return {"ok":True}

# Purpose: hub mentorship request handles the hub feature flow and returns its API result.
@router.post("/api/hub/mentorship")
async def hub_mentorship_request(request: Request,user: dict=Depends(get_current_user)):
    data=await request.json(); mentor=str(data.get("mentor","")).strip()[:120]; goal=str(data.get("goal","")).strip()[:1000]
    if not mentor or not goal: raise HTTPException(422,"Mentor name and learning goal are required")
    doc={"user_id":str(user["_id"]),"member_name":user.get("name","Member"),"mentor":mentor,"goal":goal,"status":"Pending","created_at":utcnow()}
    result=await db.hub_mentorship.insert_one(doc)
    await audit(user,"hub_mentorship_requested",str(result.inserted_id),{"mentor":mentor},request)
    return {"ok":True}

# Purpose: hub mentorship list handles the hub feature flow and returns its API result.
@router.get("/api/hub/mentorship/requests")
async def hub_mentorship_list(user: dict=Depends(get_current_user)):
    query={} if user.get("role") in HUB_STAFF else {"user_id":str(user["_id"])}
    docs=await db.hub_mentorship.find(query).sort("created_at",-1).to_list(200)
    return [{"id":str(x["_id"]),"member_name":x["member_name"],"mentor":x["mentor"],"goal":x["goal"],"status":x["status"]} for x in docs]

# Purpose: hub mentorship decision handles the hub feature flow and returns its API result.
@router.post("/api/hub/mentorship/{request_id}/decision")
async def hub_mentorship_decision(request_id: str,request: Request,user: dict=Depends(allow("Founder","Core Management","Faculty"))):
    data=await request.json(); decision=str(data.get("decision",""))
    if decision not in {"Approved","Declined"}: raise HTTPException(422,"Invalid decision")
    result=await db.hub_mentorship.update_one({"_id":oid(request_id),"status":"Pending"},{"$set":{"status":decision,"reviewed_by":user["_id"],"reviewed_at":utcnow()}})
    if not result.modified_count: raise HTTPException(409,"Request is no longer pending")
    return {"ok":True}

# Lightweight internal club inbox
# Purpose: hub messages list handles the hub feature flow and returns its API result.
@router.get("/api/hub/messages")
async def hub_messages_list(user: dict=Depends(get_current_user)):
    uid=str(user["_id"])
    docs=await db.hub_messages.find({"$or":[{"sender_id":uid},{"recipient_id":uid}]}).sort("created_at",-1).to_list(200)
    return [{"id":str(x["_id"]),"sender":x["sender_name"],"recipient":x["recipient_name"],"sender_id":x["sender_id"],"recipient_id":x["recipient_id"],"message":x["message"],"created_at":x["created_at"]} for x in docs]

# Purpose: hub message send handles the hub feature flow and returns its API result.
@router.post("/api/hub/messages")
async def hub_message_send(request: Request,user: dict=Depends(get_current_user)):
    data=await request.json(); recipient_id=str(data.get("recipient_id","")).strip(); message=str(data.get("message","")).strip()
    if not recipient_id or not message or len(message)>2000: raise HTTPException(422,"Choose a member and write a message up to 2000 characters")
    recipient=await db.users.find_one({"_id":oid(recipient_id),"status":"Active"})
    if not recipient: raise HTTPException(404,"Active recipient not found")
    doc={"sender_id":str(user["_id"]),"sender_name":user.get("name","Member"),"recipient_id":str(recipient["_id"]),"recipient_name":recipient.get("name","Member"),"message":message,"created_at":utcnow()}
    await db.hub_messages.insert_one(doc)
    await create_notification(recipient,"New TechNova message",f'{user.get("name","A member")} sent you a message.')
    return {"ok":True}

# Completion certificate record and public verification
# Purpose: hub certificate issue handles the hub feature flow and returns its API result.
@router.post("/api/hub/certificates/issue")
async def hub_certificate_issue(request: Request,user: dict=Depends(get_current_user)):
    completed=await db.tasks.count_documents({"assignee_id":user["_id"],"status":"Done"})
    if completed<1: raise HTTPException(403,"Complete at least one approved task before requesting a certificate")
    existing=await db.hub_certificates.find_one({"user_id":str(user["_id"])})
    if existing: return {"id":str(existing["_id"]),"code":existing["code"],"name":existing["name"],"completed_tasks":existing["completed_tasks"]}
    code="TN-"+token_urlsafe(9).upper()
    doc={"user_id":str(user["_id"]),"name":user.get("name","Member"),"member_id":user.get("member_id",""),"completed_tasks":completed,"code":code,"issued_at":utcnow()}
    result=await db.hub_certificates.insert_one(doc)
    await audit(user,"hub_certificate_issued",str(result.inserted_id),{"code":code},request)
    return {"id":str(result.inserted_id),"code":code,"name":doc["name"],"completed_tasks":completed}

# Purpose: hub certificate list handles the hub feature flow and returns its API result.
@router.get("/api/hub/certificates")
async def hub_certificate_list(user: dict=Depends(get_current_user)):
    docs=await db.hub_certificates.find({"user_id":str(user["_id"])}).to_list(50)
    return [{"id":str(x["_id"]),"name":x["name"],"code":x["code"],"completed_tasks":x["completed_tasks"],"issued_at":x["issued_at"]} for x in docs]

# Purpose: hub certificate verify handles the hub feature flow and returns its API result.
@router.get("/api/certificates/verify/{code}")
async def hub_certificate_verify(code: str):
    doc=await db.hub_certificates.find_one({"code":code.upper()})
    if not doc: raise HTTPException(404,"Certificate not found")
    return {"valid":True,"name":doc["name"],"member_id":doc["member_id"],"completed_tasks":doc["completed_tasks"],"issued_at":doc["issued_at"]}

# Purpose: hub active members handles the hub feature flow and returns its API result.
@router.get("/api/hub/members/active")
async def hub_active_members(user: dict=Depends(get_current_user)):
    docs=await db.users.find({"status":"Active"},{"name":1,"member_id":1,"role":1,"team":1}).sort("name",1).to_list(500)
    return [{"id":str(x["_id"]),"name":x.get("name","Member"),"member_id":x.get("member_id",""),"role":x.get("role","Member"),"team":x.get("team","Unassigned"),"status":"Active"} for x in docs]

