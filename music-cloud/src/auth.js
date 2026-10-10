const JWKS = 'https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com';
let cachedKeys = null;
let validUntil = 0;
export class AuthError extends Error {}
function decode(value) {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new AuthError();
  return Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/').padEnd(Math.ceil(value.length/4)*4,'=')),c=>c.charCodeAt(0));
}
export async function verifyFirebase(token, project, {fetcher=fetch, now=Date.now()}={}) {
  try {
    if (typeof token!=='string' || token.length>16000 || !project) throw new AuthError();
    const parts=token.split('.');
    if(parts.length!==3) throw new AuthError();
    const header=JSON.parse(new TextDecoder().decode(decode(parts[0])));
    const data=JSON.parse(new TextDecoder().decode(decode(parts[1])));
    const seconds=Math.floor(now/1000);
    if(header.alg!=='RS256' || typeof header.kid!=='string' || header.kid.length>200 ||
      data.aud!==project || data.iss!==`https://securetoken.google.com/${project}` ||
      !Number.isFinite(data.exp) || data.exp<=seconds || !Number.isFinite(data.iat) || data.iat>seconds ||
      !Number.isFinite(data.auth_time) || data.auth_time>seconds ||
      typeof data.sub!=='string' || !data.sub.length || data.sub.length>128 ||
      data.email_verified!==true || typeof data.email!=='string' ||
      data.firebase?.sign_in_provider!=='google.com') throw new AuthError();
    if(!cachedKeys || now>=validUntil) {
      const response=await fetcher(JWKS,{signal:AbortSignal.timeout(6000)});
      if(!response.ok) throw new AuthError();
      const doc=await response.json();
      if(!Array.isArray(doc.keys) || doc.keys.length>20) throw new AuthError();
      cachedKeys=doc.keys; validUntil=now+60*60*1000;
    }
    const jwk=cachedKeys.find(key=>key.kid===header.kid && key.kty==='RSA');
    if(!jwk) {validUntil=0; throw new AuthError();}
    const key=await crypto.subtle.importKey('jwk',jwk,{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
    if(!await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,decode(parts[2]),new TextEncoder().encode(`${parts[0]}.${parts[1]}`))) throw new AuthError();
    return data;
  } catch {throw new AuthError();}
}
