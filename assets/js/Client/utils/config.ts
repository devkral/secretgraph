
import { saveAs } from 'file-saver';

import { ConfigInterface, AuthInfoInterface } from "../interfaces";
import { arrToGCMKey, arrToRSAOEPkey, pwencryptprekey, pwsdecryptprekeys_first, pwsdecryptprekeys } from "./encryption";
import { b64toarr, utf8encoder } from "./misc";
import { findConfigQuery } from "../queries/content";
import { mapHashNames } from "../constants";
import { createClient } from "./graphql";
import { ApolloClient } from '@apollo/client';


export function checkConfig(config: ConfigInterface | null | undefined) {
  if(!config){
    return null;
  }
  if (
    !config.baseUrl ||
    !(config.hosts instanceof Object) ||
    !(config.tokens instanceof Object) ||
    !(config.certificates instanceof Object) ||
    !(config.configHashes instanceof Array) ||
    !config.configCluster
  ){
    console.error(config);
    return null;
  }

  return config;
}

export async function checkConfigObject(client: ApolloClient<any>, config: ConfigInterface){
  let actions : string[] = [], cert : Uint8Array | null = null;
  for(const hash of config.configHashes) {
    if(config.tokens[hash]){
      actions.push(config.tokens[hash]);
    } else if(config.certificates[hash]){
      cert = b64toarr(config.certificates[hash]);
    }
  }
  if (!actions || !cert){
    return false;
  }
  const tokens = actions.map(action => `${config.configCluster}:${action}`);
  const result = await client.query({
    query:  findConfigQuery,
    variables: {
      cluster: config.configCluster,
      authorization: tokens
    }
  });
  if (!result || result.data.contents.edges.length < 1){
    return false;
  }
  if (result.data.contents.edges.length > 1){
    console.error("Too many config objects found", result.data.contents.edges);
    return false;
  }
  return true;
}

export const loadConfigSync = (obj: Storage = window.localStorage): ConfigInterface | null => {
  let result = obj.getItem("secretgraphConfig");
  if (!result) {
    return null;
  }
  return checkConfig(JSON.parse(result));
}


export const loadConfig = async (obj: string | File | Request | Storage = window.localStorage, pws?: string[]): Promise<ConfigInterface | null> => {
  if ( obj instanceof Storage ) {
    return loadConfigSync(obj);
  } else if ( obj instanceof File ) {
    let parsedResult = JSON.parse(await obj.text());
    if (pws && parsedResult.data){
      const nonce = b64toarr(parsedResult.nonce);
      const parsedResult2 : ArrayBuffer = await pwsdecryptprekeys_first(
        parsedResult.prekeys,
        pws,
        parsedResult.iterations,
        async (data: [ArrayBuffer, string | null]) => {
          if (data[1]){
            return Promise.reject("not for decryption");
          }
          return arrToGCMKey(data[0]).then((gcmkey) => crypto.subtle.decrypt(
            {
              name: "AES-GCM",
              iv: nonce
            },
            gcmkey,
            b64toarr(parsedResult.data)
          ));
        }
      ) as any;
      return checkConfig(JSON.parse(String.fromCharCode(...new Uint8Array(parsedResult2))));
    }
    return checkConfig(parsedResult);
  } else {
    let request : Request;
    if(obj instanceof Request){
      request = obj;
    } else {
      request = new Request(obj);
    }
    const contentResult = await fetch(request);
    if (!contentResult.ok){
      return null;
    }
    const decrypturl = new URL(request.url);
    const prekeys = decrypturl.searchParams.getAll("prekey");
    decrypturl.searchParams.delete("prekey");
    if (pws){
      decrypturl.searchParams.set("keys", "")
      const decryptResult = await fetch(new Request(
        decrypturl.toString(), {
          headers: request.headers
        }
      ));
      decrypturl.searchParams.delete("keys")
      if (!decryptResult.ok || !contentResult.headers.get("X-NONCE")){
        return null;
      }
      const config = await new Promise<[CryptoKey, Uint8Array, string]>(async (resolve, reject) => {
        const queries=[];
        // support only one page
        const page = await decryptResult.json();
        for(const k of page.keys){
          if (!k.link){
            continue;
          }
          decrypturl.pathname = k.link;
          queries.push(fetch(new Request(
            decrypturl.toString(), {
              headers: request.headers
            }
          )).then(async (response) => {
            if (!response.ok || !response.headers.get("X-NONCE") || !response.headers.get("X-ITERATIONS")){
              return;
            }
            const nonce = b64toarr(response.headers.get("X-NONCE") as string);
            const respdata = await response.arrayBuffer();
            for(const iterations of (response.headers.get("X-ITERATIONS") as string).split(",")){
              try {
                return await pwsdecryptprekeys_first(
                  prekeys,
                  pws,
                  parseInt(iterations),
                  async (data: [ArrayBuffer, string | null]) => {
                      if (data[1]){
                        return Promise.reject("not for decryption");
                      }
                      return await arrToGCMKey(data[0]).then(
                      (gcmkey) => crypto.subtle.decrypt(
                        {
                          name: "AES-GCM",
                          iv: nonce
                        },
                        gcmkey,
                        respdata
                      ).then(arrToRSAOEPkey).then(
                        (key) => resolve([key, nonce, k.extra])
                      )
                    )
                  }
                );
              } finally {}
            }
          }));
        }
        await Promise.allSettled(queries);
        reject();
      }).then(
        arr => crypto.subtle.decrypt(
          {
            name: "AES-GCM",
            iv: arr[1]
          },
          arr[0],
          b64toarr(arr[2])
        ).then(arrToGCMKey)
      ).then(
        async (key) => crypto.subtle.decrypt(
          {
            name: "AES-GCM",
            iv: b64toarr(contentResult.headers.get("X-NONCE") as string)
          },
          key,
          await contentResult.arrayBuffer()
        ).then((data) => JSON.parse(String.fromCharCode(...new Uint8Array(data))))
      )
      return checkConfig(config);
    } else if(prekeys) {
      throw("requires pw but not specified");
    }
    try {
      return checkConfig(await contentResult.json());
    } catch(e) {
      console.warn(e);
      return null;
    }

  }
}

export function saveConfig(config: ConfigInterface | string, storage: Storage = window.localStorage) {
  if( typeof(config) !== "string" ) {
    config = JSON.stringify(config);
  }
  storage.setItem("secretgraphConfig", config);
}

export async function exportConfig(config: ConfigInterface | string, pws?: string[] | string, iterations?: number, name?: string) {
  let newConfig: any;
  if( pws && typeof(pws) === "string" ) {
    pws = [pws];
  }
  if( typeof(config) !== "string" ) {
    config = JSON.stringify(config);
  }
  if (pws && iterations){
    const mainnonce = crypto.getRandomValues(new Uint8Array(13));
    const mainkey = crypto.getRandomValues(new Uint8Array(32));
    const prekeys = [];
    for(const pw of pws){
      prekeys.push(
        pwencryptprekey(mainkey, pw, iterations)
      );
    }
    newConfig = JSON.stringify({
      data: await crypto.subtle.encrypt(
        {
          name: "AES-GCM",
          iv: mainnonce
        },
        await arrToGCMKey(mainkey),
        utf8encoder.encode(config)
      ).then((data) => btoa(String.fromCharCode(...new Uint8Array(data)))),
      iterations: iterations,
      nonce: btoa(String.fromCharCode(... mainnonce)),
      prekeys: await Promise.all(prekeys)
    });
  } else {
    newConfig = config;
  }
  if (!name){
    return newConfig;
  }
  saveAs(
    new File(
      [newConfig],
      name,
      {type: "text/plain;charset=utf-8"}
    )
  );
}

export async function exportConfigAsUrl(client: ApolloClient<any>, config: ConfigInterface, pw?: string) {
  let actions : string[] = [], cert : Uint8Array | null = null;
  for(const hash of config.configHashes) {
    if(config.tokens[hash]){
      actions.push(config.tokens[hash]);
    } else if(config.certificates[hash]){
      cert = b64toarr(config.certificates[hash]);
    }
  }
  if (!actions){
    return;
  }
  const tokens = actions.map(action => `${config.configCluster}:${action}`);
  const obj = await client.query({
    query:  findConfigQuery,
    variables: {
      cluster: config.configCluster,
      authorization: tokens
    }
  });
  let certhashes: string[] = [];
  if (!cert){
    return Promise.reject("no cert found");
  }
  const ckeyPromise = arrToRSAOEPkey(cert);
  certhashes = await Promise.all(obj.data.secretgraphConfig.hashAlgorithms.map(
    (hash: string) => crypto.subtle.digest(mapHashNames[hash], cert as Uint8Array).then(
      (data) => btoa(String.fromCharCode(... new Uint8Array(data)))
    )
  ));
  const searchcerthashes = new Set(actions.map(hash => `key_hash=${hash}`));
  for(const node of obj.data.contents.edges){
    if(!node.node.tags.includes("type=Config")){
      continue;
    }
    for(const keyrefnode of node.node.references.edges){
      const keyref = keyrefnode.node;
      if(keyref.target.tags.findIndex((val: any) => searchcerthashes.has(val)) == -1){
        continue;
      }
      const privkeyrefnode = keyref.target.references.find((node: any) => node.node.target.tags);
      if(!privkeyrefnode){
        continue;
      }
      const privkeykey = privkeyrefnode.node.target.tags.find((tag: string) => "key=").split("=", 1)[1];
      const url = new URL(config.baseUrl);
      const decrypttoken = await crypto.subtle.decrypt(
        {
          name: "RSA-OAEP",
        },
        await ckeyPromise,
        b64toarr(privkeykey)
      )

      if (pw) {
        const decrypttoken2 = crypto.subtle.decrypt(
          {
            name: "RSA-OAEP",
          },
          await ckeyPromise,
          b64toarr(keyref.extra)
        )
        const prekey = await pwencryptprekey(
          decrypttoken,
          pw,
          obj.data.secretgraphConfig.PBKDF2Iterations
        );
        const prekey2 = await pwencryptprekey(
          await decrypttoken2,
          pw,
          obj.data.secretgraphConfig.PBKDF2Iterations
        );
        return `${url.origin}${node.node.link}?decrypt&token=${tokens.join("token=")}&prekey=${certhashes[0]}:${prekey}&prekey=shared:${prekey2}`
      } else {
        return `${url.origin}${node.node.link}?decrypt&token=${tokens.join("token=")}&token=${certhashes[0]}:${btoa(String.fromCharCode(... new Uint8Array(decrypttoken)))}`
      }
    }
  }
  throw Error("no config content found")
}


export function extractAuthInfo(config: ConfigInterface, url: string) : AuthInfoInterface {
  const keys = [];
  const hashes = [];
  const clusters = config.hosts[(new URL(url, window.location.href)).href].clusters;
  for (const id in clusters) {
    const clusterconf = clusters[id];
    for (const hash in clusterconf.hashes){
      // const actions = clusterconf.hashes[hash]
      if (config.tokens[hash]){
        hashes.push(hash);
        keys.push(`${id}:${config.tokens[hash]}`);
      }
    }
  }
  return {hashes, keys};
}


export function findCertCandidatesForRefs(config: ConfigInterface, nodeData: any) : [Uint8Array, Uint8Array][] {
  const found: [Uint8Array, Uint8Array][] = [];
  for(const _refnode in nodeData.references){
    const refnode =  nodeData.references[_refnode];
    for(const _dirtyhash of refnode.target.tags){
      const dirtyhash = refnode.target.tag[_dirtyhash];
      const cleanhash = dirtyhash.split("=", 2)[1];
      if(cleanhash && config.certificates[cleanhash]){
        found.push([
          b64toarr(config.certificates[cleanhash]),
          b64toarr(refnode.extra)
        ]);
      }
    }
  }
  return found;
}
