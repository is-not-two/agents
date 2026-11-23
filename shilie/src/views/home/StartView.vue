<script setup lang="ts">
import { Activity, ArrowRight } from "lucide-vue-next";
import { useTheme } from "@/stores/theme";
const theme = useTheme();
</script>

<template>
  <main class="start-screen">
    <header class="start-bar">
      <span class="wordmark"><span class="mark" aria-hidden="true">时</span><strong>时列</strong></span>
      <button type="button" class="icon-button" :aria-label="theme.animated ? '关闭动效' : '开启动效'"
        :aria-pressed="!theme.animated" :disabled="theme.reduced" @click="theme.toggleMotion()"><Activity :size="18" /></button>
    </header>
    <section class="start-stage" aria-labelledby="start-title">
      <svg class="start-orbits" viewBox="0 0 960 620" fill="none" aria-hidden="true" focusable="false">
        <defs>
          <radialGradient id="start-halo">
            <stop stop-color="#fffaf4" stop-opacity=".94" />
            <stop offset=".56" stop-color="#fff6f0" stop-opacity=".45" />
            <stop offset="1" stop-color="#f2c4d0" stop-opacity="0" />
          </radialGradient>
          <linearGradient id="start-trail" x1="130" y1="520" x2="810" y2="110" gradientUnits="userSpaceOnUse">
            <stop stop-color="#a76b6e" stop-opacity=".20" />
            <stop offset=".46" stop-color="#aa6e87" stop-opacity=".66" />
            <stop offset="1" stop-color="#bf7c4a" stop-opacity=".64" />
          </linearGradient>
        </defs>
        <circle cx="480" cy="310" r="275" fill="url(#start-halo)" />
        <g stroke="url(#start-trail)" stroke-width="1.25">
          <ellipse class="start-trail" cx="480" cy="310" rx="370" ry="133" transform="rotate(-22 480 310)" pathLength="100" />
          <ellipse class="start-trail start-trail--later" cx="480" cy="310" rx="354" ry="155" transform="rotate(22 480 310)" pathLength="100" />
          <ellipse class="start-trail start-trail--last" cx="480" cy="310" rx="290" ry="215" transform="rotate(-8 480 310)" pathLength="100" />
        </g>
        <g class="start-stars">
          <circle cx="137" cy="382" r="5" fill="#b87f83"/><circle cx="751" cy="154" r="6" fill="#d2a269"/>
          <circle cx="785" cy="425" r="5" fill="#b17e99"/><circle cx="259" cy="459" r="4" fill="#c18a73"/>
          <circle cx="666" cy="493" r="4" fill="#a583a2"/><circle cx="310" cy="131" r="4" fill="#c79274"/>
          <path d="M187 207v20m-10-10h20M777 286v20m-10-10h20M602 105v16m-8-8h16M387 511v16m-8-8h16"
            stroke="#ba8b88" stroke-width="1.5" stroke-linecap="round"/>
        </g>
      </svg>
      <div class="start-center">
        <p class="hero-kicker"><span></span> 个人工作区</p>
        <h1 id="start-title">时列</h1>
        <p>把每一步，留在这里。</p>
        <RouterLink class="primary start-button" to="/workspace">开始 <ArrowRight :size="18" aria-hidden="true" /></RouterLink>
      </div>
    </section>
  </main>
</template>
