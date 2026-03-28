use anyhow::Result;
use beu::protocol::Protocol;

fn main() -> Result<()> {
    tracing_subscriber::fmt::init();
    Protocol::run()
}
