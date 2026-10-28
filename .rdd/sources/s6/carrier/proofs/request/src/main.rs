use rdd_contracts::qualification::v1::{ProbeService,EchoRequest,EchoResponse};
struct Provider;
impl ProbeService for Provider { async fn echo(&self,_:EchoResponse)->EchoResponse{EchoResponse::default()} }
fn consumer<P:ProbeService>(p:&P,r:EchoRequest)->impl std::future::Future<Output=EchoResponse>+Send+'_ {p.echo(r)}
fn main(){let p=Provider;let _future=consumer(&p,EchoRequest::default());}
