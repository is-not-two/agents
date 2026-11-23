<script setup lang="ts">
import {computed} from "vue";
const props=defineProps<{text:string}>();
const parts=computed(()=>{
 const out:{text:string;href?:string}[]=[];let last=0;
 for(const match of props.text.matchAll(/https?:\/\/[^\s<>"'，。；！？【】]+/giu)){
  const raw=match[0].replace(/[),.;:!?）]+$/u,"");
  try{const url=new URL(raw);if(!url.hostname||url.username||url.password)continue;
   out.push({text:props.text.slice(last,match.index)},{text:raw,href:url.href});last=match.index!+raw.length;
  }catch{continue}
 }
 out.push({text:props.text.slice(last)});return out;
});
</script>
<template><div class="prose"><template v-for="(part,index) in parts" :key="index"><a v-if="part.href" :href="part.href" target="_blank" rel="noopener noreferrer nofollow ugc">{{part.text}}</a><template v-else>{{part.text}}</template></template></div></template>
