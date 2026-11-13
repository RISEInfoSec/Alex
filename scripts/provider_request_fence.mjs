// This historical script has not been integrated with the shared private
// provider coordinator. Fail closed before any OpenAlex send.
export function requireCoordinatedProvider(url){
 const host=new URL(url).hostname.toLowerCase().replace(/\.+$/,'');
 if(host==='openalex.org'||host.endsWith('.openalex.org'))throw Error('OpenAlex requires the shared private coordinator');
}
