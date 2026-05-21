const voices = ["alloy","ash","ballad","coral","echo","fable","nova","onyx","sage","shimmer","verse","marin","cedar"];
const defaultSpeakers = [
  {id:"S1",name:"主持人A",role:"理性介绍",voice:"marin",style:"自然、清晰、像知识型短视频主持人"},
  {id:"S2",name:"主持人B",role:"宝妈体验",voice:"nova",style:"温柔、有亲和力、带一点惊喜和真实体验感"},
  {id:"S3",name:"主持人C",role:"补充观点",voice:"cedar",style:"简洁、有节奏"},
  {id:"S4",name:"主持人D",role:"总结收束",voice:"shimmer",style:"温暖、鼓励"}
];

const el = id => document.getElementById(id);
const scriptEl = el("scriptText");
scriptEl.addEventListener("input", ()=> el("charCount").textContent = scriptEl.value.length);

function renderSpeakers(){
  const mode = el("narrationMode").value;
  const count = {monologue:1, dialogue2:2, dialogue3:3, dialogue4:4}[mode] || 2;
  const wrap = el("speakerConfigs"); wrap.innerHTML = "";
  for(let i=0;i<count;i++){
    const s = defaultSpeakers[i];
    const div = document.createElement("div"); div.className = "role-card";
    div.innerHTML = `<label>角色名称<input data-k='name' value='${s.name}'></label>
      <label>角色身份<input data-k='role' value='${s.role}'></label>
      <label>声音<select data-k='voice'>${voices.map(v=>`<option ${v===s.voice?'selected':''}>${v}</option>`).join("")}</select></label>
      <label>语气说明<input data-k='style' value='${s.style}'></label>`;
    div.dataset.id = s.id;
    wrap.appendChild(div);
  }
}
el("narrationMode").addEventListener("change", renderSpeakers);
renderSpeakers();

el("images").addEventListener("change", (e)=>{
  const files = [...e.target.files];
  el("imgCount").textContent = files.length;
  const p = el("previews"); p.innerHTML="";
  files.forEach(f=>{
    const img = document.createElement("img");
    img.src = URL.createObjectURL(f); p.appendChild(img);
  });
});

function collect(){
  const speakers = [...document.querySelectorAll("#speakerConfigs .role-card")].map(card=>({
    id: card.dataset.id,
    name: card.querySelector("[data-k='name']").value,
    role: card.querySelector("[data-k='role']").value,
    voice: card.querySelector("[data-k='voice']").value,
    style: card.querySelector("[data-k='style']").value,
  }));
  return {
    scriptText: el("scriptText").value,
    hashtags: el("hashtags").value,
    orientation: el("orientation").value,
    durationMode: el("durationMode").value,
    customDuration: el("customDuration").value,
    videoStyle: el("videoStyle").value,
    subtitleMode: el("subtitleMode").value,
    showSpeakerName: el("showSpeakerName").checked,
    narrationMode: el("narrationMode").value,
    dialogueStyle: el("dialogueStyle").value,
    emotionLevel: el("emotionLevel").value,
    speechSpeed: el("speechSpeed").value,
    imageStrategy: el("imageStrategy").value,
    apiProvider: el("apiProvider").value,
    openaiApiKey: el("openaiApiKey").value,
    openaiBaseUrl: el("openaiBaseUrl").value,
    scriptModel: el("scriptModel").value,
    ttsModel: el("ttsModel").value,
    imageModel: el("imageModel").value,
    imageQuality: el("imageQuality").value,
    enableAiImage: el("enableAiImage").checked,
    speakerConfigs: speakers
  };
}

el("previewBtn").onclick = ()=>{
  const d = collect();
  const key = d.openaiApiKey || "";
  d.openaiApiKey = key.length > 8 ? `${key.slice(0,4)}****${key.slice(-4)}` : "";
  el("preview").textContent = JSON.stringify(d, null, 2);
};

async function poll(taskId){
  const box = el("taskStatus");
  const timer = setInterval(async ()=>{
    const res = await fetch(`/api/task/${taskId}`);
    const d = await res.json();
    box.textContent = `task_id=${taskId} | ${d.status} | ${d.progress}% | ${d.message}${d.error?` | ${d.error}`:""}`;
    if(d.status === "success"){
      clearInterval(timer);
      el("videoWrap").innerHTML = `<a href='${d.video_url}' target='_blank'>下载视频</a><video controls src='${d.video_url}'></video>`;
    }
    if(d.status === "failed") clearInterval(timer);
  }, 2000);
}

el("generateBtn").onclick = async ()=>{
  const d = collect();
  if(el("saveLocal").checked) localStorage.setItem("saved_api_key", d.openaiApiKey);
  const fd = new FormData();
  Object.entries(d).forEach(([k,v])=> fd.append(k, typeof v === "object" ? JSON.stringify(v) : String(v)));
  [...el("images").files].forEach(f=> fd.append("images", f));
  const res = await fetch("/api/generate-video", { method:"POST", body:fd });
  const j = await res.json();
  if(!j.success){ alert(j.error || "提交失败"); return; }
  poll(j.task_id);
};

window.addEventListener("load", ()=>{
  const saved = localStorage.getItem("saved_api_key");
  if(saved) el("openaiApiKey").value = saved;
});
