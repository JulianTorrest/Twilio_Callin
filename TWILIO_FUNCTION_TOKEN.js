// Twilio Function para generar Access Tokens para WebRTC
// Despliega esta función en: https://console.twilio.com/us1/develop/functions/services

exports.handler = function(context, event, callback) {
  const AccessToken = Twilio.jwt.AccessToken;
  const VoiceGrant = AccessToken.VoiceGrant;

  // Obtener identidad del agente (cédula)
  const identity = event.identity || 'agente_default';

  // Crear token con tiempo de vida de 1 hora
  const token = new AccessToken(
    context.ACCOUNT_SID,
    context.TWILIO_API_KEY,
    context.TWILIO_API_SECRET,
    { 
      identity: identity,
      ttl: 3600 // 1 hora
    }
  );

  // Crear Voice Grant
  const voiceGrant = new VoiceGrant({
    outgoingApplicationSid: context.TWIML_APP_SID,
    incomingAllow: true, // Permitir llamadas entrantes
  });

  // Agregar grant al token
  token.addGrant(voiceGrant);

  // Preparar respuesta
  const response = new Twilio.Response();
  response.appendHeader('Content-Type', 'application/json');
  response.appendHeader('Access-Control-Allow-Origin', '*'); // CORS
  response.setBody({ 
    token: token.toJwt(),
    identity: identity
  });
  
  callback(null, response);
};

/* 
VARIABLES DE ENTORNO REQUERIDAS EN TWILIO FUNCTION:

1. ACCOUNT_SID - Se obtiene automáticamente
2. TWILIO_API_KEY - Crear en: https://console.twilio.com/us1/account/keys-credentials/api-keys
3. TWILIO_API_SECRET - Se genera al crear el API Key (guárdalo de forma segura)
4. TWIML_APP_SID - Crear TwiML App en: https://console.twilio.com/us1/develop/voice/manage/twiml-apps

PASOS PARA CONFIGURAR:

1. Crear API Key:
   - Ve a: https://console.twilio.com/us1/account/keys-credentials/api-keys
   - Click "Create API Key"
   - Friendly Name: "Dialer WebRTC Key"
   - Key Type: "Standard"
   - Click "Create"
   - GUARDA el SID y el SECRET (no podrás verlo después)

2. Crear TwiML App:
   - Ve a: https://console.twilio.com/us1/develop/voice/manage/twiml-apps
   - Click "Create new TwiML App"
   - Friendly Name: "Camacol Dialer"
   - Voice Request URL: [Tu TWILIO_FUNCTION_URL actual]
   - Voice Method: POST
   - Click "Save"
   - COPIA el Application SID (empieza con AP...)

3. Desplegar esta Function:
   - Ve a: https://console.twilio.com/us1/develop/functions/services
   - Click "Create Service"
   - Service Name: "dialer-token-service"
   - Click "Add +" para agregar función
   - Path: /token
   - Pega este código
   - En "Environment Variables" agrega:
     * TWILIO_API_KEY = [tu API Key SID]
     * TWILIO_API_SECRET = [tu API Secret]
     * TWIML_APP_SID = [tu TwiML App SID]
   - Click "Deploy All"

4. Obtener URL de la Function:
   - Después del deploy, copia la URL
   - Será algo como: https://dialer-token-service-XXXX.twil.io/token
   - Esta URL la usarás en el código de Streamlit

5. Probar la Function:
   - Abre: https://dialer-token-service-XXXX.twil.io/token?identity=1121871773
   - Deberías ver: {"token":"eyJ...","identity":"1121871773"}

ACTUALIZAR EN STREAMLIT:
En app.py línea 303, reemplaza:
fetch('TU_TWILIO_FUNCTION_TOKEN_URL?identity={st.session_state.agente_id}')

Por:
fetch('https://dialer-token-service-XXXX.twil.io/token?identity={st.session_state.agente_id}')
*/
