'use client';

import { useEffect, useState } from 'react';

import LandingPage from './landing-page';
import AppShell from './workspace/app-shell';

export default function VegetationApp() {
  const [workspace,setWorkspace]=useState(false);
  useEffect(()=>{
    const sync=()=>setWorkspace(window.location.hash==='#workspace');
    sync();window.addEventListener('hashchange',sync);return()=>window.removeEventListener('hashchange',sync);
  },[]);
  const open=()=>setWorkspace(true);
  const home=()=>{window.location.hash='';setWorkspace(false);};
  return workspace?<AppShell onHome={home}/>:<LandingPage onOpen={open}/>;
}
