import React, { useEffect, useState } from "react";
import { BriefcaseBusiness, Code2, CalendarDays, BookOpen, MessageSquare, Gift, Plus, ExternalLink, Trophy, Zap, Users, Send, Archive, ClipboardCheck } from "lucide-react";

const API = (import.meta.env.VITE_API_BASE_URL || "https://technova-5h0g.onrender.com").replace(/\/$/, "");
const sections = [
  ["projects","Projects",BriefcaseBusiness],["challenges","Coding Arena",Code2],
  ["events","Events",CalendarDays],["resources","Library",BookOpen],["polls","Polls",ClipboardCheck],
  ["discussions","Community",MessageSquare],["rewards","Rewards",Gift],["attendance","Attendance",ClipboardCheck],["mentorship","Mentorship",Users],["messages","Messages",MessageSquare],["certificates","Certificates",Trophy],
];
const emptyForm = {title:"",description:"",category:"",url:"",due_date:"",points:0};

export default function TechNovaHub({token,user}) {
  const [section,setSection]=useState("projects");
  const [data,setData]=useState({});
  const [profile,setProfile]=useState(null);
  const [form,setForm]=useState(emptyForm);
  const [showForm,setShowForm]=useState(false);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [code,setCode]=useState({});
  const [language,setLanguage]=useState("C");
  const [comment,setComment]=useState({});
  const [attendanceCode,setAttendanceCode]=useState("");
  const [sessionTitle,setSessionTitle]=useState("");
  const [rewardRequests,setRewardRequests]=useState([]);
  const [pollOptions,setPollOptions]=useState("Yes,No");
  const [mentor,setMentor]=useState("");
  const [goal,setGoal]=useState("");
  const [mentorshipRequests,setMentorshipRequests]=useState([]);
  const [messages,setMessages]=useState([]);
  const [members,setMembers]=useState([]);
  const [recipientId,setRecipientId]=useState("");
  const [messageText,setMessageText]=useState("");
  const [certificates,setCertificates]=useState([]);
  const staff=["Founder","Core Management","Faculty"].includes(user?.role);
  const call=async(path,opts={})=>{
    const res=await fetch(API+"/api"+path,{...opts,headers:{"Content-Type":"application/json",Authorization:"Bearer "+token,...(opts.headers||{})}});
    const body=await res.json().catch(()=>({}));
    if(!res.ok) throw new Error(body.detail||"Request failed ("+res.status+")");
    return body;
  };
  const refresh=async()=>{
    setError("");
    try {
      const [p,...lists]=await Promise.all([
        call("/hub/profile"),
        ...sections.filter(([key])=>!["attendance","mentorship","messages","certificates"].includes(key)).map(([key])=>call("/hub/"+key)),
        call("/hub/attendance"),
        call("/hub/rewards/requests"),
        call("/hub/mentorship/requests"),
        call("/hub/messages"),
        call("/members"),
        call("/hub/certificates")
      ]);
      setProfile(p);
      const listSections=sections.filter(([key])=>!["attendance","mentorship","messages","certificates"].includes(key));
      setData({...Object.fromEntries(listSections.map(([key],i)=>[key,lists[i]])),attendance:lists[listSections.length]});
      setRewardRequests(lists[listSections.length+1]);
      setMentorshipRequests(lists[listSections.length+2]);
      setMessages(lists[listSections.length+3]);
      setMembers(lists[listSections.length+4]);
      setCertificates(lists[listSections.length+5]);
      setData(v=>({...v,attendance:lists[listSections.length],mentorship:lists[listSections.length+2],messages:lists[listSections.length+3],certificates:lists[listSections.length+5]}));
    } catch(e){setError(e.message);}
  };
  useEffect(()=>{if(token)refresh();},[token]);
  const create=async(e)=>{
    e.preventDefault();setBusy(true);setError("");setMessage("");
    try{await call("/hub/"+section,{method:"POST",body:JSON.stringify({...form,options:section==="polls"?pollOptions.split(",").map(x=>x.trim()).filter(Boolean):[]})});setForm(emptyForm);setShowForm(false);setMessage("Published successfully.");await refresh();}
    catch(e){setError(e.message);}finally{setBusy(false);}
  };
  const join=async(id)=>{
    try{await call("/hub/projects/"+id+"/join",{method:"POST"});setMessage("You joined the project.");await refresh();}
    catch(e){setError(e.message);}
  };
  const submit=async(id)=>{
    try{await call("/hub/challenges/"+id+"/submit",{method:"POST",body:JSON.stringify({code:code[id]||"",language})});setMessage("Code submitted for review.");setCode(v=>({...v,[id]:""}));}
    catch(e){setError(e.message);}
  };
  const addComment=async(id)=>{
    try{await call("/hub/discussions/"+id+"/comment",{method:"POST",body:JSON.stringify({message:comment[id]||""})});setComment(v=>({...v,[id]:""}));await refresh();}
    catch(e){setError(e.message);}
  };
  const items=data[section]||[];
  const checkIn=async(e)=>{e.preventDefault();try{await call("/hub/attendance/check-in",{method:"POST",body:JSON.stringify({code:attendanceCode})});setAttendanceCode("");setMessage("Attendance recorded.");await refresh();}catch(e){setError(e.message);}};
  const openAttendance=async(e)=>{e.preventDefault();try{const session=await call("/hub/attendance",{method:"POST",body:JSON.stringify({title:sessionTitle})});setSessionTitle("");setMessage("Session opened. Share code: "+session.code);await refresh();}catch(e){setError(e.message);}};
  const rsvp=async(id)=>{try{await call("/hub/events/"+id+"/rsvp",{method:"POST"});setMessage("Event registration saved.");await refresh();}catch(e){setError(e.message);}};
  const requestReward=async(id)=>{try{await call("/hub/rewards/"+id+"/request",{method:"POST"});setMessage("Reward request sent.");await refresh();}catch(e){setError(e.message);}};
  const vote=async(id,option)=>{try{await call("/hub/polls/"+id+"/vote",{method:"POST",body:JSON.stringify({option})});setMessage("Vote recorded.");await refresh();}catch(e){setError(e.message);}};
  const sendMessage=async(e)=>{e.preventDefault();try{await call("/hub/messages",{method:"POST",body:JSON.stringify({recipient_id:recipientId,message:messageText})});setMessage("Message sent.");setMessageText("");await refresh();}catch(e){setError(e.message);}};
  const requestMentorship=async(e)=>{e.preventDefault();try{await call("/hub/mentorship",{method:"POST",body:JSON.stringify({mentor,goal})});setMessage("Mentorship request sent.");setMentor("");setGoal("");await refresh();}catch(e){setError(e.message);}};
  const issueCertificate=async()=>{try{await call("/hub/certificates/issue",{method:"POST"});setMessage("Certificate issued.");await refresh();}catch(e){setError(e.message);}};
  const decideMentorship=async(id,decision)=>{try{await call("/hub/mentorship/"+id+"/decision",{method:"POST",body:JSON.stringify({decision})});await refresh();}catch(e){setError(e.message);}};
  const decideReward=async(id,decision)=>{try{await call("/hub/rewards/requests/"+id+"/decision",{method:"POST",body:JSON.stringify({decision})});await refresh();}catch(e){setError(e.message);}};
  const reviewChallenge=async(item,userId,decision)=>{try{await call("/hub/challenges/"+item.id+"/review",{method:"POST",body:JSON.stringify({user_id:userId,decision,feedback:decision==="Accepted"?"Approved by club management":"Please revise and resubmit."})});setMessage("Challenge submission reviewed.");await refresh();}catch(e){setError(e.message);}};
  const canCreate=(staff&&["projects","challenges","events","resources","polls","rewards"].includes(section))||section==="discussions";
  return <main className="hub-page">
    <div className="hub-hero">
      <div><span className="hub-eyebrow">TECHNOVA ECOSYSTEM</span><h1>Club Hub</h1><p>Build projects, sharpen skills, learn together and grow as a developer.</p></div>
      <div className="hub-level"><div className="hub-level-icon"><Trophy/></div><div><b>Level {profile?.level||1}</b><small>{profile?.xp||0} XP · {profile?.credits||0} credits</small></div></div>
    </div>
    {profile&&<div className="hub-stats">
      <div><span>Experience</span><b>{profile.xp} XP</b><small>Next level: {profile.next_level_xp} XP</small></div>
      <div><span>Completed tasks</span><b>{profile.completed_tasks}</b><small>{profile.pending_reviews} awaiting review</small></div>
      <div><span>Achievements</span><b>{profile.achievements.length}</b><small>Milestones unlocked</small></div>
    </div>}
    {profile?.achievements?.length>0&&<section className="hub-achievements"><h3>Achievements unlocked</h3><div>{profile.achievements.map(a=><article key={a.title}><strong>{a.icon}</strong><b>{a.title}</b><small>{a.description}</small></article>)}</div></section>}
    <div className="hub-sectionbar"><div className="hub-tabs">{sections.map(([key,label,Icon])=><button key={key} className={section===key?"active":""} onClick={()=>setSection(key)}><Icon size={16}/>{label}</button>)}</div>
      {canCreate&&<button className="primary hub-add" onClick={()=>setShowForm(v=>!v)}><Plus size={16}/> Create</button>}
    </div>
    {error&&<div className="hub-alert error">{error}</div>}{message&&<div className="hub-alert">{message}</div>}
    {section==="polls"&&showForm&&<div className="hub-create"><label>Poll options (comma separated)<input value={pollOptions} onChange={e=>setPollOptions(e.target.value)} placeholder="Option A, Option B"/></label></div>}
    {section==="mentorship"&&<form className="hub-create" onSubmit={requestMentorship}><h3>Request a mentor</h3><input required placeholder="Mentor name" value={mentor} onChange={e=>setMentor(e.target.value)}/><textarea required rows="3" placeholder="What do you want to learn?" value={goal} onChange={e=>setGoal(e.target.value)}/><button className="primary">Send request</button></form>}
    {section==="messages"&&<form className="hub-create" onSubmit={sendMessage}><h3>Send a club message</h3><select required value={recipientId} onChange={e=>setRecipientId(e.target.value)}><option value="">Choose active member</option>{members.filter(m=>m.status==="Active"&&m.id!==user?.id).map(m=><option key={m.id} value={m.id}>{m.name} · {m.member_id}</option>)}</select><textarea required maxLength="2000" rows="3" placeholder="Write a message…" value={messageText} onChange={e=>setMessageText(e.target.value)}/><button className="primary">Send message</button></form>}
    {section==="certificates"&&<div className="hub-create"><h3>Achievement certificates</h3><p>Request a certificate after completing at least one approved task.</p><button className="primary" onClick={issueCertificate}>Issue my certificate</button>{certificates.map(c=><article key={c.id}><b>{c.name}</b><small>{c.completed_tasks} approved tasks · Verification code: {c.code}</small><a className="hub-link" href={API+"/api/certificates/verify/"+c.code} target="_blank" rel="noreferrer">Verify certificate <ExternalLink size={13}/></a></article>)}</div>}
    {section==="attendance"&&<div className="hub-create">
      {staff&&<form onSubmit={openAttendance}><h3>Open attendance session</h3><input required minLength="3" placeholder="Meeting / workshop title" value={sessionTitle} onChange={e=>setSessionTitle(e.target.value)}/><button className="primary">Generate check-in code</button></form>}
      <form onSubmit={checkIn}><h3>Member check-in</h3><input required placeholder="Enter code shared by management" value={attendanceCode} onChange={e=>setAttendanceCode(e.target.value)}/><button className="primary">Confirm attendance</button></form>
    </div>}
    {showForm&&section!=="attendance"&&<form className="hub-create" onSubmit={create}><h3>Create {sections.find(x=>x[0]===section)?.[1]}</h3>
      <input required minLength="3" placeholder="Title" value={form.title} onChange={e=>setForm(v=>({...v,title:e.target.value}))}/>
      <textarea placeholder="Description and details" rows="3" value={form.description} onChange={e=>setForm(v=>({...v,description:e.target.value}))}/>
      <div className="hub-form-grid"><input placeholder="Category / technology" value={form.category} onChange={e=>setForm(v=>({...v,category:e.target.value}))}/><input placeholder="Resource / GitHub URL (optional)" type="url" value={form.url} onChange={e=>setForm(v=>({...v,url:e.target.value}))}/><input type="date" value={form.due_date} onChange={e=>setForm(v=>({...v,due_date:e.target.value}))}/>{section==="challenges"&&<input type="number" min="0" max="1000" placeholder="Points" value={form.points} onChange={e=>setForm(v=>({...v,points:Number(e.target.value)}))}/>}</div>
      <div className="hub-form-actions"><button type="button" className="secondary" onClick={()=>setShowForm(false)}>Cancel</button><button className="primary" disabled={busy}>{busy?"Publishing…":"Publish"}</button></div>
    </form>}
    <div className="hub-grid">{items.length===0?<div className="hub-empty"><Code2 size={30}/><b>No {sections.find(x=>x[0]===section)?.[1].toLowerCase()} yet</b><span>{staff?"Create the first item to get the club started.":"Check back when club management publishes something."}</span></div>:items.map(item=><article className="hub-card" key={item.id}>
      <div className="hub-card-top"><span>{item.category||sections.find(x=>x[0]===section)?.[1]}</span><small>{item.status}</small></div><h3>{item.title}</h3><p>{item.description||"No description provided."}</p>
      <div className="hub-meta">{item.created_by&&<span>By {item.created_by}</span>}{item.due_date&&<span>Due {item.due_date}</span>}{item.points>0&&<span>{item.points} points</span>}{section==="projects"&&<span><Users size={13}/> {item.members?.length||0} members</span>}</div>
      {section==="projects"&&<button className="secondary" onClick={()=>join(item.id)}>Join project</button>}
      {section==="events"&&<button className="secondary" onClick={()=>rsvp(item.id)}>Register for event</button>}
      {section==="polls"&&(item.options||[]).map(option=><button className="secondary" key={option} onClick={()=>vote(item.id,option)}>{option} · {(item.votes||[]).filter(v=>v.option===option).length} votes</button>)}
      {section==="rewards"&&<button className="secondary" onClick={()=>requestReward(item.id)}>Request reward</button>}
      {section==="attendance"&&<div className="hub-meta"><span>{item.attendee_count} checked in</span><span>{item.checked_in?"You are checked in":"Check in with session code"}</span>{staff&&item.code&&<b>Code: {item.code}</b>}</div>}
      {section==="challenges"&&staff&&(item.submissions||[]).map((sub,i)=><div className="hub-review" key={i}><b>{sub.member_name} · {sub.language}</b><small>{sub.review_status}</small><pre>{sub.code}</pre>{sub.review_feedback&&<p>{sub.review_feedback}</p>}<div><button className="secondary" onClick={()=>reviewChallenge(item,sub.user_id,"Accepted")}>Accept</button><button className="secondary" onClick={()=>reviewChallenge(item,sub.user_id,"Needs changes")}>Request changes</button></div></div>)}
      {section==="challenges"&&<div className="hub-submit"><select value={language} onChange={e=>setLanguage(e.target.value)}><option>C</option><option>C++</option><option>Python</option><option>Java</option><option>JavaScript</option></select><textarea rows="5" placeholder="Paste your solution code…" value={code[item.id]||""} onChange={e=>setCode(v=>({...v,[item.id]:e.target.value}))}/><button className="primary" onClick={()=>submit(item.id)}>Submit solution</button><small>Submissions are stored for review. No code is executed on the server.</small></div>}
      {section==="discussions"&&<div className="hub-comments">{(item.comments||[]).map((c,i)=><p key={i}><b>{c.name}:</b> {c.message}</p>)}<div><input placeholder="Add a comment…" value={comment[item.id]||""} onChange={e=>setComment(v=>({...v,[item.id]:e.target.value}))}/><button onClick={()=>addComment(item.id)} aria-label="Send comment"><Send size={15}/></button></div></div>}
      {item.url&&<a className="hub-link" href={item.url} target="_blank" rel="noreferrer">Open link <ExternalLink size={14}/></a>}
    </article>)}</div>
    {section==="mentorship"&&<section className="hub-achievements"><h3>Mentorship requests</h3>{mentorshipRequests.map(r=><article key={r.id}><b>{r.member_name} → {r.mentor}</b><small>{r.goal} · {r.status}</small>{staff&&r.status==="Pending"&&<span><button className="secondary" onClick={()=>decideMentorship(r.id,"Approved")}>Approve</button><button className="secondary" onClick={()=>decideMentorship(r.id,"Declined")}>Decline</button></span>}</article>)}</section>}
    {section==="messages"&&<section className="hub-achievements"><h3>Inbox and sent messages</h3>{messages.map(m=><article key={m.id}><b>{m.sender_id===user?.id?"To: "+m.recipient:"From: "+m.sender}</b><small>{m.message}</small></article>)}</section>}
        {section==="rewards"&&<section className="hub-achievements"><h3>Reward request history</h3>{rewardRequests.length===0?<small>No reward requests yet.</small>:rewardRequests.map(r=><article key={r.id}><b>{r.reward_title}</b><small>{r.member_name||"Member"} · {r.status}</small>{staff&&r.status==="Pending"&&<span><button className="secondary" onClick={()=>decideReward(r.id,"Approved")}>Approve</button> <button className="secondary" onClick={()=>decideReward(r.id,"Declined")}>Decline</button></span>}</article>)}</section>}
    <div className="hub-footnote"><Zap size={15}/> XP is calculated from approved task completions. Online code execution, AI assistance and GitHub account linking need separately configured secure providers.</div>
  </main>;
}
