import{c as t,j as i}from"./index-B8aa3_pV.js";import{C as d}from"./circle-check-DlMpoOMq.js";import{S as l}from"./shield-alert-DYaItuRr.js";/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const p=t("CircleDashed",[["path",{d:"M10.1 2.182a10 10 0 0 1 3.8 0",key:"5ilxe3"}],["path",{d:"M13.9 21.818a10 10 0 0 1-3.8 0",key:"11zvb9"}],["path",{d:"M17.609 3.721a10 10 0 0 1 2.69 2.7",key:"1iw5b2"}],["path",{d:"M2.182 13.9a10 10 0 0 1 0-3.8",key:"c0bmvh"}],["path",{d:"M20.279 17.609a10 10 0 0 1-2.7 2.69",key:"1ruxm7"}],["path",{d:"M21.818 10.1a10 10 0 0 1 0 3.8",key:"qkgqxc"}],["path",{d:"M3.721 6.391a10 10 0 0 1 2.7-2.69",key:"1mcia2"}],["path",{d:"M6.391 20.279a10 10 0 0 1-2.69-2.7",key:"1fvljs"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const h=t("CircleX",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["path",{d:"m15 9-6 6",key:"1uzhvr"}],["path",{d:"m9 9 6 6",key:"z0biqf"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const k=t("Clock3",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["polyline",{points:"12 6 12 12 16.5 12",key:"1aq6pp"}]]);function u({value:a}){const e=a===!0?"pass":a===!1?"fail":String(a??"na").toLowerCase(),s=new Set(["pass","passed","completed","ok","true"]),c=new Set(["fail","failed","error","false"]),n=new Set(["running","queued","awaiting_input","awaiting_confirmation","pending"]),r=s.has(e)?d:c.has(e)?h:n.has(e)?k:e==="blocked"?l:p,o=s.has(e)?"success":c.has(e)?"danger":n.has(e)?"warning":e==="blocked"?"danger":"neutral";return i.jsxs("span",{className:`status-badge ${o}`,children:[i.jsx(r,{size:13,"aria-hidden":"true"}),e.replaceAll("_"," ")]})}export{k as C,u as S};
