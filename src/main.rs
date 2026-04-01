use anyhow::Result;
use beu::protocol::Protocol;

fn main() -> Result<()> {
    beu::observability::init();
    Protocol::run()
}
