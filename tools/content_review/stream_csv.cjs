'use strict';

// Strict bounded CSV reader for public upstream inventories. It handles UTF-8
// across chunks, quoted commas/newlines and CRLF. Unsupported malformed input
// fails closed rather than guessing at candidate identities.
const MAX_ROWS=50000,MAX_FIELD=32*1024*1024,MAX_COLUMNS=512;
class CsvRows{
 constructor(onRow){
  if(typeof onRow!=='function')throw Error('CSV consumer unavailable');
  this.onRow=onRow;this.decoder=new TextDecoder('utf-8',{fatal:true});this.field='';this.row=[];this.header=null;
  this.state='start';this.skipLf=false;this.started=false;this.count=0;this.closed=false;
 }
 pushField(){if(this.field.length>MAX_FIELD||this.row.length>=MAX_COLUMNS)throw Error('CSV field or column limit exceeded');this.row.push(this.field);this.field='';}
 pushRow(){
  if(!this.started&&this.row.length===0&&this.field==='')return;
  this.pushField();
  if(this.header===null){
   if(!this.row.length||!this.row.includes('candidate_id')||this.row.some(x=>!x)||new Set(this.row).size!==this.row.length)
    throw Error('CSV header invalid');
   this.header=this.row;
  }else{
   if(this.row.length>this.header.length||this.count>=MAX_ROWS)throw Error('CSV row or count invalid');
   const selected=Object.create(null);
   for(const key of ['candidate_id','title','doi','source_url','link']){
    const index=this.header.indexOf(key);if(index>=0)selected[key]=index<this.row.length?this.row[index]:null;
   }
   this.onRow(selected,this.count++);
  }
  this.row=[];this.field='';this.started=false;this.state='start';
 }
 text(value){
  for(let i=0;i<value.length;i++){
   const c=value[i];
   if(this.skipLf){this.skipLf=false;if(c==='\n')continue;}
   if(this.state==='quoted'){
    if(c==='"')this.state='after_quote';else this.field+=c;
   }else if(this.state==='after_quote'){
    if(c==='"'){this.field+='"';this.state='quoted';}
    else if(c===','){this.pushField();this.state='start';}
    else if(c==='\r'||c==='\n'){this.pushRow();this.skipLf=c==='\r';}
    else throw Error('Malformed quoted CSV field');
   }else if(this.state==='start'&&c==='"'){this.started=true;this.state='quoted';}
   else if(c===','){this.started=true;this.pushField();this.state='start';}
   else if(c==='\r'||c==='\n'){this.pushRow();this.skipLf=c==='\r';}
   else{this.started=true;this.field+=c;this.state='plain';}
   if(this.field.length>MAX_FIELD)throw Error('CSV field limit exceeded');
  }
 }
 update(bytes){if(this.closed||!(bytes instanceof Uint8Array))throw Error('Invalid CSV stream');this.text(this.decoder.decode(bytes,{stream:true}));}
 finish(){
  if(this.closed)throw Error('CSV stream already closed');this.closed=true;this.text(this.decoder.decode());
  if(this.state==='quoted')throw Error('Unterminated quoted CSV field');
  this.pushRow();if(!this.header)throw Error('CSV header unavailable');
  return {rows:this.count};
 }
}
module.exports={CsvRows};
