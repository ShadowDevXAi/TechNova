import React, { useEffect, useState } from "react";
import { BriefcaseBusiness, Code2, CalendarDays, BookOpen, MessageSquare, Gift, Plus, ExternalLink, Trophy, Zap, Users, Send, Archive } from "lucide-react";

const API = (import.meta.env.VITE_API_BASE_URL || "https://technova-5h0g.onrender.com").replace(/\/$/, "");
const sections = [
  ["projects","Projects",BriefcaseBusiness],["challenges","Coding Arena",Code2],
  ["events","Events",CalendarDays],["resources","Library",BookOpen],
  ["discussions","Community",MessageSquare],["rewards","Rewards",Gift],
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
        ...sections.map(([key])=>call("/hub/"+key))
      ]);
      setProfile(p);
      setData(Object.fromEntries(sections.map(([key],i)=>[key,lists[i]])));
    } catch(e){setError(e.message);}
  };
  useEffect(()=>{if(token)refresh();},[token]);
  const create=async(e)=>{
    e.preventDefault();setBusy(true);setError("");setMessage("");
    try{await call("/hub/"+section,{method:"POST",body:JSON.stringify(form)});setForm(emptyForm);setShowForm(false);setMessage("Published successfully.");await refresh();}
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
  const canCreate=staff||section==="discussions";
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
    {showForm&&<form className="hub-create" onSubmit={create}><h3>Create {sections.find(x=>x[0]===section)?.[1]}</h3>
      <input required minLength="3" placeholder="Title" value={form.title} onChange={e=>setForm(v=>({...v,title:e.target.value}))}/>
      <textarea placeholder="Description and details" rows="3" value={form.description} onChange={e=>setForm(v=>({...v,description:e.target.value}))}/>
      <div className="hub-form-grid"><input placeholder="Category / technology" value={form.category} onChange={e=>setForm(v=>({...v,category:e.target.value}))}/><input placeholder="Resource / GitHub URL (optional)" type="url" value={form.url} onChange={e=>setForm(v=>({...v,url:e.target.value}))}/><input type="date" value={form.due_date} onChange={e=>setForm(v=>({...v,due_date:e.target.value}))}/>{section==="challenges"&&<input type="number" min="0" max="1000" placeholder="Points" value={form.points} onChange={e=>setForm(v=>({...v,points:Number(e.target.value)}))}/>}</div>
      <div className="hub-form-actions"><button type="button" className="secondary" onClick={()=>setShowForm(false)}>Cancel</button><button className="primary" disabled={busy}>{busy?"Publishing…":"Publish"}</button></div>
    </form>}
    <div className="hub-grid">{items.length===0?<div className="hub-empty"><Code2 size={30}/><b>No {sections.find(x=>x[0]===section)?.[1].toLowerCase()} yet</b><span>{staff?"Create the first item to get the club started.":"Check back when club management publishes something."}</span></div>:items.map(item=><article className="hub-card" key={item.id}>
      <div className="hub-card-top"><span>{item.category||sections.find(x=>x[0]===section)?.[1]}</span><small>{item.status}</small></div><h3>{item.title}</h3><p>{item.description||"No description provided."}</p>
      <div className="hub-meta">{item.created_by&&<span>By {item.created_by}</span>}{item.due_date&&<span>Due {item.due_date}</span>}{item.points>0&&<span>{item.points} points</span>}{section==="projects"&&<span><Users size={13}/> {item.members?.length||0} members</span>}</div>
      {section==="projects"&&<button className="secondary" onClick={()=>join(item.id)}>Join project</button>}
      {section==="challenges"&&<div className="hub-submit"><select value={language} onChange={e=>setLanguage(e.target.value)}><option>C</option><option>C++</option><option>Python</option><option>Java</option><option>JavaScript</option></select><textarea rows="5" placeholder="Paste your solution code…" value={code[item.id]||""} onChange={e=>setCode(v=>({...v,[item.id]:e.target.value}))}/><button className="primary" onClick={()=>submit(item.id)}>Submit solution</button><small>Submissions are stored for review. No code is executed on the server.</small></div>}
      {section==="discussions"&&<div className="hub-comments">{(item.comments||[]).map((c,i)=><p key={i}><b>{c.name}:</b> {c.message}</p>)}<div><input placeholder="Add a comment…" value={comment[item.id]||""} onChange={e=>setComment(v=>({...v,[item.id]:e.target.value}))}/><button onClick={()=>addComment(item.id)} aria-label="Send comment"><Send size={15}/></button></div></div>}
      {item.url&&<a className="hub-link" href={item.url} target="_blank" rel="noreferrer">Open link <ExternalLink size={14}/></a>}
    </article>)}</div>
    <div className="hub-footnote"><Zap size={15}/> XP is calculated from approved task completions. Online code execution, AI assistance and GitHub account linking need separately configured secure providers.</div>
  </main>;
}
