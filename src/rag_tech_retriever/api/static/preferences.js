// 只保存界面偏好；不读写知识、规划或数据库状态。
const densityNames=['紧凑','标准','宽松'];
const densityKeys=['compact','standard','comfortable'];
const preferenceKey='zhixing.display-density';
export function setupPreferences() {
  const menu=document.querySelector('#appearance-menu'), slider=document.querySelector('#density'), output=document.querySelector('#density-value');
  function apply(value,persist=false) {
    const index=Number(value); if(!Number.isInteger(index)||index<0||index>2)return;
    document.documentElement.dataset.density=densityKeys[index];slider.value=String(index);
    output.value=densityNames[index];slider.setAttribute('aria-valuetext',densityNames[index]);
    slider.style.setProperty('--range-fill',`${index*50}%`);
    if(persist){try{localStorage.setItem(preferenceKey,String(index));}catch{/* 浏览器不允许存储时仍可即时调节。 */}}
  }
  let stored=null;try{stored=localStorage.getItem(preferenceKey);}catch{}
  apply(stored!==null&&/^[0-2]$/.test(stored)?stored:1);
  slider.addEventListener('input',()=>apply(slider.value,true));
  document.querySelector('#density-reset').addEventListener('click',()=>apply(1,true));
  document.addEventListener('pointerdown',event=>{if(menu.open&&!menu.contains(event.target))menu.open=false;});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&menu.open){menu.open=false;menu.querySelector('summary').focus();}});
  window.addEventListener('storage',event=>{if(event.key===preferenceKey)apply(event.newValue!==null&&/^[0-2]$/.test(event.newValue)?event.newValue:1);});
}
