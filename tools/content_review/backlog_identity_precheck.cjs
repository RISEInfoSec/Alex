'use strict';
// Read-only conservative screening. A clear result is never a gate pass: the
// Site must independently re-read, re-audit and fence the actual checkpoint.
const identity=require('./conservative_identity.cjs');
let raw='';process.stdin.setEncoding('utf8');
process.stdin.on('data',x=>raw+=x).on('end',()=>{
 try{
  const v=JSON.parse(raw);let profile;
  try{profile=identity.profile(v.candidate)}catch{process.stdout.write('unsupported');return}
  for(const row of v.comparisons){if(identity.possiblyMatches(profile,row)){process.stdout.write('held');return}}
  process.stdout.write('clear');
 }catch{process.stdout.write('unavailable');process.exitCode=1}
});
