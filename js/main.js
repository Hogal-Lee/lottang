// ---------- 에러 로거 ----------
window.addEventListener('error', e=>{
  const p=document.querySelector('.panel'); if(p) p.textContent='오류: '+(e.message||e.type);
});
window.addEventListener('unhandledrejection', e=>{
  const p=document.querySelector('.panel'); if(p) p.textContent='작업 실패: '+(e.reason&&e.reason.message?e.reason.message:e.reason);
});

// ---------- 유틸 ----------
function v0(x){ x=Number(x); return isFinite(x)?x:0; }
function colorFor(s){ if(s>=15)return'#DC2626'; if(s>=10)return'#7C3AED'; if(s>=5)return'#2563EB'; if(s>=2)return'#60A5FA'; return'#9CA3AF' }
function markerImage(color){
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><circle cx="10" cy="10" r="7" fill="${color}" stroke="white" stroke-width="2"/></svg>`;
  return new kakao.maps.MarkerImage('data:image/svg+xml;charset=UTF-8,'+encodeURIComponent(svg), new kakao.maps.Size(20,20), {offset:new kakao.maps.Point(10,10)});
}
function debounce(fn,wait){let t;return(...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),wait)}}
async function shareUrlDirect(url, panel){
  if(navigator.share){ try{ await navigator.share({title:'LoTTang',url}); panel.textContent='공유 창을 열었습니다.'; return; }catch(e){} }
  try{ await navigator.clipboard.writeText(url); panel.textContent='공유 링크 복사 완료'; return; }catch(e){}
  try{ const ta=document.createElement('textarea'); ta.value=url; ta.style.position='fixed'; ta.style.left='-9999px';
       document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
       panel.textContent='공유 링크 복사 완료'; }catch{ panel.textContent='복사 실패. 주소창 URL을 복사해주세요.'; }
}

// ---------- 앱 ----------
kakao.maps.load(function(){
  const panel=document.querySelector('.panel');

  // 1) 데이터 먼저 로드
  fetch('./data/stores_clean.geojson', {cache:'no-store'})
    .then(r=>{ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
    .then(geo=>{
      const features=(geo&&geo.features)?geo.features:[];
      panel.textContent='매장 데이터 '+features.length+'개 로드됨';

      // 2) 지도/클러스터/컨트롤
      const map=new kakao.maps.Map(document.getElementById('map'),{center:new kakao.maps.LatLng(37.5665,126.9780),level:6});
      const infowindow=new kakao.maps.InfoWindow({zIndex:10});
      kakao.maps.event.addListener(map,'click',()=>infowindow.close());

      const clusterer=new kakao.maps.MarkerClusterer({map,averageCenter:true,minLevel:7,disableClickZoom:false});

      // Controls
      const qEl=document.getElementById('q'), guEl=document.getElementById('gu'), only1El=document.getElementById('only1st');
      const minEl=document.getElementById('minScore'), minVal=document.getElementById('minScoreVal');
      const countEl=document.getElementById('count');
      const sortKeyEl=document.getElementById('sortKey') || { value:'score' };

      // Guide toggle (모바일)
      const guide=document.querySelector('.score-guide');
      const btnGuide=document.getElementById('btnGuide');
      if(btnGuide) btnGuide.addEventListener('click', ()=> guide.classList.toggle('open'));

      // FAB & Sheet
      const fabLocate=document.getElementById('fabLocate');
      const fabShare=document.getElementById('fabShare');
      const sheet=document.getElementById('sheet');
      const handle=document.getElementById('sheetHandle');
      const bsList=document.getElementById('bsList');
      const bsCount=document.getElementById('bsCount');

      function isMobile(){return window.matchMedia('(max-width:768px)').matches}
      function syncMobile(){
        const on=isMobile();
        if (fabLocate) fabLocate.style.display=on?'flex':'none';
        if (fabShare)  fabShare.style.display =on?'flex':'none';
      }
      syncMobile(); window.addEventListener('resize', syncMobile);

      // FABs
      if(fabLocate) fabLocate.addEventListener('click', ()=>document.getElementById('locate').click());
      if(fabShare)  fabShare.addEventListener('click', ()=>shareUrlDirect(location.href, panel));
      const btnShare=document.getElementById('share');
      if(btnShare) btnShare.addEventListener('click', ()=>shareUrlDirect(location.href, panel));

      // Sheet toggle + light drag
      function sheetOpen(){ if(sheet) sheet.classList.add('open'); }
      function sheetClose(){ if(sheet) sheet.classList.remove('open'); }
      if(handle){
        handle.addEventListener('click', ()=>{ sheet.classList.contains('open')?sheetClose():sheetOpen(); });
        let dragging=false, startY=0;
        handle.addEventListener('touchstart',e=>{ if(!isMobile())return; dragging=true; startY=e.touches[0].clientY; sheet.style.transition='none';},{passive:true});
        handle.addEventListener('touchmove',e=>{ if(!dragging)return; const dy=e.touches[0].clientY-startY; if(dy<-12) sheetOpen(); if(dy>12) sheetClose();},{passive:true});
        handle.addEventListener('touchend',()=>{ dragging=false; sheet.style.transition='';});
      }

      // Markers & filters
      let markerObjs=[]; // {marker,pos,props}
      function popupHtml(p){
        return `<div style="padding:8px;line-height:1.5;min-width:220px">
          <div style="font-weight:600">${p.name||''}</div>
          <div style="color:#374151">${p.address||''}</div>
          <div style="margin-top:6px;font-size:13px;color:#111">
            1등: <b>${v0(p.win1)}</b> | 2등: <b>${v0(p.win2)}</b> | 점수: <b>${v0(p.score)}</b>
          </div></div>`;
      }
      function applyFilters(){
        const kw=qEl.value.trim(), gu=guEl.value; const only1=!!only1El.checked; const minS=parseFloat(minEl.value||'0');
        minVal.textContent=minS.toFixed(1);

        clusterer.clear(); markerObjs.forEach(o=>o.marker.setMap(null)); markerObjs=[];
        const filtered=features.filter(f=>{
          const p=f.properties||{}, name=(p.name||'')+'', addr=(p.address||'')+'';
          const score=v0(p.score), w1=v0(p.win1);
          if(kw && !(name.includes(kw)||addr.includes(kw))) return false;
          if(gu && !addr.includes(gu)) return false;
          if(only1 && w1<=0) return false;
          if(score<minS) return false;
          return true;
        });
        const markers=filtered.map(f=>{
          const [lon,lat]=f.geometry.coordinates; const p=f.properties||{};
          const pos=new kakao.maps.LatLng(lat,lon); const img=markerImage(colorFor(v0(p.score)));
          const m=new kakao.maps.Marker({position:pos,image:img});
          kakao.maps.event.addListener(m,'click',()=>{infowindow.setContent(popupHtml(p));infowindow.open(map,m);});
          markerObjs.push({marker:m,pos,props:p}); return m;
        });
        clusterer.addMarkers(markers);
        countEl.textContent=filtered.length+'개';
        updateTop20();
        updateGuideCounts();
        return filtered;
      }

      function visibleMarkers(){
        const b=map.getBounds();
        return markerObjs.filter(o=>b && b.contain(o.pos));
      }

      // Top20 (sheet + desktop)
      function updateTop20(){
        const key=(sortKeyEl && sortKeyEl.value) || 'score';
        const vis=visibleMarkers();
        const top=vis.sort((a,b)=>{
          const av=v0(a.props[key]), bv=v0(b.props[key]);
          if(bv!==av) return bv-av;
          const as=v0(a.props.score), bs=v0(b.props.score);
          if(bs!==as) return bs-as;
          return (''+a.props.name).localeCompare(''+b.props.name);
        }).slice(0,20);

        if(bsCount) bsCount.textContent=top.length+'개';
        if(bsList){
          bsList.innerHTML='';
          top.forEach((o,idx)=>{
            const p=o.props;
            const el=document.createElement('div'); el.className='item'; el.style.margin='6px 0';
            el.innerHTML=`<div class="name">${idx+1}. ${p.name||''}</div>
                          <div class="addr">${p.address||''}</div>
                          <div class="meta">1등 ${v0(p.win1)} · 2등 ${v0(p.win2)} · 점수 ${v0(p.score)}</div>`;
            el.addEventListener('click',()=>{ map.panTo(o.pos); infowindow.setContent(popupHtml(p)); infowindow.open(map,o.marker); });
            bsList.appendChild(el);
          });
        }
        const sidebarList=document.getElementById('sidebarList');
        const sidebarCount=document.getElementById('sidebarCount');
        if(sidebarList && sidebarCount){
          sidebarCount.textContent=top.length+'개';
          sidebarList.innerHTML='';
          top.forEach((o,idx)=>{
            const p=o.props; const el=document.createElement('div'); el.className='item';
            el.innerHTML=`<div class="name">${idx+1}. ${p.name||''}</div>
                          <div class="addr">${p.address||''}</div>
                          <div class="meta">1등 ${v0(p.win1)} · 2등 ${v0(p.win2)} · 점수 ${v0(p.score)}</div>`;
            el.addEventListener('click',()=>{map.panTo(o.pos);infowindow.setContent(popupHtml(p));infowindow.open(map,o.marker);});
            sidebarList.appendChild(el);
          });
        }
      }

      // Legend counts
      const cnt0to2=document.getElementById('cnt0to2');
      const cnt2to5=document.getElementById('cnt2to5');
      const cnt5to10=document.getElementById('cnt5to10');
      const cnt10to15=document.getElementById('cnt10to15');
      const cnt15=document.getElementById('cnt15');
      function updateGuideCounts(){
        const b=map.getBounds(); let c0=0,c2=0,c5=0,c10=0,c15n=0;
        markerObjs.forEach(o=>{
          if(!b.contain(o.pos)) return;
          const s=v0(o.props.score);
          if(s>=15)c15n++; else if(s>=10)c10++; else if(s>=5)c5++; else if(s>=2)c2++; else c0++;
        });
        if(cnt0to2){cnt0to2.textContent=c0} if(cnt2to5){cnt2to5.textContent=c2}
        if(cnt5to10){cnt5to10.textContent=c5} if(cnt10to15){cnt10to15.textContent=c10}
        if(cnt15){cnt15.textContent=c15n}
      }

      // Events
      qEl.addEventListener('input', debounce(()=>{applyFilters();},250));
      guEl.addEventListener('change', ()=>applyFilters());
      only1El.addEventListener('change', ()=>applyFilters());
      minEl.addEventListener('input', ()=>applyFilters());
      if(sortKeyEl && sortKeyEl.addEventListener) sortKeyEl.addEventListener('change', updateTop20);
      kakao.maps.event.addListener(map,'idle', debounce(()=>{updateTop20();updateGuideCounts();},150));

      // 현재 위치
      document.getElementById('locate').addEventListener('click', ()=>{
        if(!navigator.geolocation){ panel.textContent='현재 위치: 브라우저 미지원'; return; }
        panel.textContent='현재 위치 확인 중…';
        navigator.geolocation.getCurrentPosition((pos)=>{
          const lat=pos.coords.latitude, lon=pos.coords.longitude, acc=pos.coords.accuracy||100;
          const here=new kakao.maps.LatLng(lat,lon); map.panTo(here); map.setLevel(4);
          const dot='data:image/svg+xml;charset=UTF-8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><circle cx="10" cy="10" r="6" fill="#2563EB" stroke="white" stroke-width="2"/></svg>');
          new kakao.maps.Marker({position:here,image:new kakao.maps.MarkerImage(dot,new kakao.maps.Size(20,20),{offset:new kakao.maps.Point(10,10)}),map});
          panel.textContent='현재 위치 표시 (±'+Math.round(acc)+'m)';
        },()=>{ panel.textContent='현재 위치 실패'; },{enableHighAccuracy:true,timeout:7000,maximumAge:0});
      });

      // 초기 렌더
      applyFilters();
    })
    .catch(err=>{
      const p=document.querySelector('.panel');
      p.textContent='데이터 로드 실패: '+err.message;
      console.error(err);
    });
});
