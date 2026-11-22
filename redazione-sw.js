// =====================================================================================
// Service worker della Redazione AI LA28 · versione 1.0 (22/11/2026, scheda 52)
// Va nel repo map-q-la28, nella stessa cartella di redazione.html.
//
// Cos'è un «service worker»: un piccolo programma che il browser (o l'iPhone) tiene pronto
// anche quando la pagina è chiusa. Qui serve SOLO a ricevere le notifiche push di Firebase
// Cloud Messaging e a mostrarle. Non salva pagine e non cambia il funzionamento del sito.
// =====================================================================================

// le librerie di Firebase nella versione «compat», l'unica che si può caricare in un service worker
importScripts("https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.14.1/firebase-messaging-compat.js");

// la stessa configurazione di redazione.html (valori NON segreti)
firebase.initializeApp({
  apiKey: "AIzaSyAr6K6l5o3hCzq2woc54Sx5XmDGKd9e8vU",
  authDomain: "redazione-la28.firebaseapp.com",
  projectId: "redazione-la28",
  storageBucket: "redazione-la28.firebasestorage.app",
  messagingSenderId: "875557376372",
  appId: "1:875557376372:web:1ce4e8593cc93a92319c21",
});

// Basta «accendere» Firebase Messaging: quando arriva una notifica con titolo e testo
// (lo script redazione.py la manda così) e la pagina è chiusa, Firebase la mostra da solo.
// Toccandola si apre la redazione (indirizzo scritto dallo script nel campo «link»).
firebase.messaging();
