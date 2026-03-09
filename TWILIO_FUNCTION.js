exports.handler = function(context, event, callback) {
  // 1. Inicializar la respuesta de voz (TwiML)
  const twiml = new Twilio.twiml.VoiceResponse();

  // 2. Detectar si es llamada WebRTC (desde navegador) o Server-Side
  const isWebRTC = event.From && event.From.startsWith('client:');
  
  console.log('=== TWILIO FUNCTION INICIADA ===');
  console.log('From:', event.From);
  console.log('To:', event.To);
  console.log('Is WebRTC:', isWebRTC);

  // 3. Mensaje inicial (Voz natural en español)
  twiml.say({
    language: 'es-MX',
    voice: 'Polly.Andres'
  }, 'Bienvenido. Esta llamada está siendo grabada para fines de calidad y métricas. Por favor, espere un momento.');

  // 4. Configurar Marcación con Grabación y Métricas
  const dial = twiml.dial({
    record: 'record-from-answer',  // Graba desde que contesta
    recordingStatusCallback: context.DOMAIN_NAME + '/recording-status',  // Webhook para notificar cuando esté lista la grabación
    answerOnBridge: true,  // Solo cobra cuando el destino contesta
    timeLimit: 3600,  // 1 hora máximo (ya no hay límite de trial)
    callerId: event.From  // Mantener el Caller ID original
  });

  // 5. Número de destino DINÁMICO
  // Viene desde app.py cuando se hace la llamada
  const numeroDestino = event.To;
  
  if (!numeroDestino) {
    twiml.say({
      language: 'es-MX',
      voice: 'Polly.Andres'
    }, 'Error: No se especificó un número de destino.');
    console.error('ERROR: No se recibió número de destino');
    return callback(null, twiml);
  }

  // 6. Marcar al número destino
  dial.number(numeroDestino);

  console.log('Llamada procesada hacia:', numeroDestino);
  console.log('=== FIN TWILIO FUNCTION ===');

  // 7. Retornar el TwiML a Twilio para ejecutar la llamada
  return callback(null, twiml);
};
