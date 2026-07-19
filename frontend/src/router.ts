import { createRouter, createWebHistory } from 'vue-router'

import HomeView from './views/HomeView.vue'
import DraftView from './views/DraftView.vue'
import NoteView from './views/NoteView.vue'
import PreviewView from './views/PreviewView.vue'
import WordView from './views/WordView.vue'

export default createRouter({
  history: createWebHistory('/app/'),
  routes: [
    { path: '/', component: HomeView },
    { path: '/words/:word', component: WordView },
    { path: '/drafts/:id', component: DraftView },
    { path: '/notes/:id', component: NoteView },
    { path: '/notes/:id/preview', component: PreviewView },
  ],
})
